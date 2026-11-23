"""Blender bridge client (pure Python, no bpy): detect which way an agent can reach Blender, send code to a live
session over either socket protocol, or run a skill script headless and parse its tagged JSON line.

Usage (plain Python 3.9+; prints exactly one line `BRIDGE_CLIENT <json>`; exit code 0 = ok, 1 = failure):
    python bridge_client.py detect [--host localhost] [--ports 9876,9877] [--timeout 3] [--tools "name1,name2"]
                                   [--no-exe] [--exe-version]
    python bridge_client.py exec [--host localhost] --port 9876 [--protocol auto|official|blender-mcp]
                                 (--code "..." | --file x.py) [--opts '{"k": 1}' | --opts-file o.json]
                                 [--opts-name X_OPTS] [--timeout 120] [--probe-timeout 3]
    python bridge_client.py run-cli [--blender PATH] [--blend f.blend] [--factory-startup] [--timeout 600]
                                    (--script x.py [-- script args] | --code "..." | --file x.py
                                     [--opts '{"k": 1}' | --opts-file o.json] [--opts-name X_OPTS])

Protocols (both default to localhost:9876 -- only one can own the port):
  official     Blender Lab "MCP" extension (Blender 5.1+). One request per TCP connection:
               UTF-8 JSON {"type": "execute", "code": str, "strict_json": bool} + b"\\0"
               -> JSON + b"\\0": {"status": "ok"|"error", "result": dict, "message": str, "stdout": str, "stderr": str}.
               The code must leave a dict in the global `result`.
  blender-mcp  Community add-on (github.com/ahujasid/blender-mcp). Persistent connection, NO delimiter: the reader
               accumulates bytes until they parse as JSON. {"type": "execute_code", "params": {"code": str}}
               -> {"status": "success"|"error", "result": {"executed": true, "result": <captured stdout>}}.
               Only stdout comes back, so exec wraps the code to print `__BRIDGE_RESULT__<json of result>`.
Sending one protocol to the other server hangs (missing NUL / trailing NUL never parses). `detect` uses one
connection: send {"type": "ping"} without NUL (community replies), wait ~40% of --timeout, then send b"\\0"
(official replies "Unknown request type"), so a wrong or silent listener costs at most --timeout seconds.

exec with --file/--opts sends: `<OPTS_NAME> = json.loads(...)`, `__file__ = path`, then the file compiled under its
own filename (tracebacks show real line numbers). The opts name is read from the script itself (the first
`globals().get("X")` / `"X" in globals()` it contains: bake_maps.py -> BAKE_OPTS, uv_tools.py -> UV_OPTS,
viewport_capture.py -> VIEWPORT_CAPTURE_OPTS); `<FILE_STEM_UPPER>_OPTS` is the fallback; --opts-name overrides.
run-cli --script runs `blender -b [--factory-startup] [blend] --python x.py -- args` and returns the last stdout
line shaped `<TAG> {json}` (prefers the tag == script stem upper). run-cli --code/--file runs the same exec wrapper
headless and reads the `__BRIDGE_RESULT__` line.

Limitations: cannot see the agent's MCP tool list (pass it via --tools); a long operation (bake, render) blocks the
live session's main thread for its duration -- use run-cli for those; the official server evicts a client that has
not finished sending a request within ~10 s, and replies are processed on Blender's timer (0.05-1 s latency).
"""
import argparse
import glob
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time

TAG = "BRIDGE_CLIENT"
RESULT_TAG = "__BRIDGE_RESULT__"
DEFAULT_PORTS = [9876]
PROBE_CODE = (
    "import bpy\n"
    "def _v3d():\n"
    "    try:\n"
    "        return sum(1 for w in bpy.context.window_manager.windows for a in w.screen.areas if a.type == 'VIEW_3D')\n"
    "    except Exception:\n"
    "        return 0\n"
    "result = {'blender': bpy.app.version_string, 'background': bpy.app.background,\n"
    "          'filepath': bpy.data.filepath, 'is_dirty': bpy.data.is_dirty, 'view3d_areas': _v3d(),\n"
    "          'mode': getattr(bpy.context, 'mode', None),\n"
    "          'scene': bpy.context.scene.name if bpy.context.scene else None,\n"
    "          'objects': len(bpy.data.objects)}\n"
)

# MCP tool names that identify a bridge (client prefixes such as "Blender:" or "mcp__blender__" are stripped).
TOOL_SIGNATURES = {
    "official": {"execute_blender_code_for_cli", "get_screenshot_of_area_as_image", "get_screenshot_of_window_as_image",
                 "render_viewport_to_path", "render_thumbnail_to_path", "get_objects_summary",
                 "get_object_detail_summary", "get_blendfile_summary_datablocks", "search_api_docs",
                 "search_manual_docs", "get_python_api_docs", "jump_to_view3d_object_by_name"},
    "blender-mcp": {"get_scene_info", "get_object_info", "get_viewport_screenshot", "get_polyhaven_status",
                    "search_polyhaven_assets", "download_polyhaven_asset", "set_texture", "get_hyper3d_status",
                    "get_sketchfab_status", "search_sketchfab_models", "generate_hyper3d_model_via_text",
                    "get_polypizza_status", "get_hunyuan3d_status", "get_addon_status"},
}
CAPABILITIES = {
    "official": {"live_ui_context": "yes (timer on main thread; find VIEW_3D via window_manager.windows)",
                 "return_values": "dict in global `result` (non-JSON values repr'd when strict_json=false)",
                 "stdout": "captured and returned", "screenshots": "get_screenshot_of_area_as_image tool, or "
                 "render.opengl / screen.screenshot_area from code", "long_running": "blocks UI; deferred reply "
                 "via global check_is_finished() (interactive only, 1 h cap); prefer run-cli",
                 "headless_variant": "blender -b --command blender_mcp --port N (needs extension enabled, "
                 "--online-mode)", "framing": "JSON + NUL, one request per connection"},
    "blender-mcp": {"live_ui_context": "yes (queue drained by a main-thread timer)",
                    "return_values": "stdout only -> print JSON (bridge_client adds a tagged print of `result`)",
                    "stdout": "is the result", "screenshots": "get_viewport_screenshot tool (offscreen draw), or "
                    "render.opengl from code", "long_running": "blocks UI; MCP-side socket timeout 180 s; prefer run-cli",
                    "headless_variant": "none (add-on refuses to start in background mode)",
                    "framing": "bare JSON, persistent connection, parse-until-valid"},
    "cli": {"live_ui_context": "no (sculpt/paint/gesture ops fail poll or crash)", "return_values": "tagged stdout "
            "line", "stdout": "captured", "screenshots": "render to file (Workbench/EEVEE), then read the PNG",
            "long_running": "yes (subprocess timeout)", "headless_variant": "is headless", "framing": "process"},
}


def emit(data, ok=True):
    print(TAG + " " + json.dumps(data, default=str))
    return 0 if ok else 1


# ---------------------------------------------------------------- sockets
def _addr(host):
    # Both add-ons bind AF_INET; "localhost" may try ::1 first (about 2 s refused-retry on Windows).
    return "127.0.0.1" if host == "localhost" else host


def _recv_until(sock, deadline, done):
    buf = bytearray()
    while time.monotonic() < deadline:
        sock.settimeout(max(0.01, deadline - time.monotonic()))
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        except OSError:
            break
        if not chunk:
            return buf, True
        buf.extend(chunk)
        if done(buf):
            return buf, False
    return buf, False


def _json_complete(buf):
    try:
        json.loads(bytes(buf).decode("utf-8"))
        return True
    except (ValueError, UnicodeDecodeError):
        return False


def classify_reply(buf):
    raw = bytes(buf)
    framed = raw.endswith(b"\0")
    text = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
    try:
        msg = json.loads(text)
    except ValueError:
        return "unknown", None
    if not isinstance(msg, dict):
        return "unknown", msg
    st, m = msg.get("status"), str(msg.get("message", ""))
    if framed or st == "ok" or "Unknown request type" in m or "strict_json" in m:
        return "official", msg
    if st == "success" or "Unknown command type" in m:
        return "blender-mcp", msg
    return "unknown", msg


def probe_protocol(host, port, timeout=3.0):
    """Identify the protocol on host:port within `timeout` seconds using one harmless connection."""
    t0 = time.monotonic()
    deadline = t0 + timeout
    out = {"host": host, "port": port}
    try:
        sock = socket.create_connection((_addr(host), port), timeout=min(1.0, timeout))
    except ConnectionRefusedError:
        return {**out, "protocol": "closed", "elapsed_s": round(time.monotonic() - t0, 3)}
    except OSError as ex:
        return {**out, "protocol": "closed", "error": str(ex), "elapsed_s": round(time.monotonic() - t0, 3)}
    with sock:
        try:
            sock.sendall(json.dumps({"type": "ping", "params": {}}).encode("utf-8"))
            phase1 = min(deadline, t0 + 0.4 * timeout)
            buf, closed = _recv_until(sock, phase1, _json_complete)
            if not buf and not closed:
                try:
                    sock.sendall(b"\0")
                except OSError:
                    closed = True
                if not closed:
                    more, closed = _recv_until(sock, deadline, lambda b: b"\0" in b or _json_complete(b))
                    buf.extend(more)
        except OSError as ex:
            return {**out, "protocol": "unknown", "error": str(ex), "elapsed_s": round(time.monotonic() - t0, 3)}
    proto, msg = classify_reply(buf) if buf else ("unknown", None)
    res = {**out, "protocol": proto, "elapsed_s": round(time.monotonic() - t0, 3)}
    if not buf:
        res["note"] = "listener accepted but never replied (not a Blender bridge, or Blender busy/frozen)"
    elif proto == "unknown":
        res["reply_head"] = bytes(buf[:120]).decode("utf-8", "replace")
    return res


def send_official(host, port, code, timeout=120.0, strict_json=False, connect_timeout=3.0):
    req = (json.dumps({"type": "execute", "code": code, "strict_json": strict_json}) + "\0").encode("utf-8")
    sock = socket.create_connection((_addr(host), port), timeout=connect_timeout)
    with sock:
        sock.sendall(req)
        buf, closed = _recv_until(sock, time.monotonic() + timeout, lambda b: b"\0" in b)
    if b"\0" not in buf:
        raise TimeoutError("no NUL-terminated reply within %.1fs (%d bytes%s) -- wrong protocol, or Blender busy"
                           % (timeout, len(buf), ", connection closed" if closed else ""))
    return json.loads(bytes(buf).split(b"\0", 1)[0].decode("utf-8"))


def send_blender_mcp(host, port, command, params=None, timeout=120.0, connect_timeout=3.0):
    sock = socket.create_connection((_addr(host), port), timeout=connect_timeout)
    with sock:
        sock.sendall(json.dumps({"type": command, "params": params or {}}).encode("utf-8"))
        buf, closed = _recv_until(sock, time.monotonic() + timeout, _json_complete)
    if not _json_complete(buf):
        raise TimeoutError("no complete JSON reply within %.1fs (%d bytes%s) -- wrong protocol, or Blender busy"
                           % (timeout, len(buf), ", connection closed" if closed else ""))
    return json.loads(bytes(buf).decode("utf-8"))


# ---------------------------------------------------------------- code wrapping
OPTS_IN_SCRIPT = re.compile(r'globals\(\)\.get\(\s*"([A-Z][A-Z0-9_]*)"|"([A-Z][A-Z0-9_]*)"\s+in\s+globals\(\)'
                            r'|globals\(\)\[\s*"([A-Z][A-Z0-9_]*)"')


def default_opts_name(path):
    """Name of the options global a skill script reads: taken from the script text (first `globals().get("X")` /
    `"X" in globals()` / `globals()["X"]`), falling back to <FILE_STEM_UPPER>_OPTS. Most scripts use a short
    name (BAKE_OPTS, UV_OPTS, RIG_OPTS ...), so the filename convention alone would miss them."""
    stem = os.path.splitext(os.path.basename(path))[0] if path else "SCRIPT"
    fallback = re.sub(r"\W", "_", stem).upper() + "_OPTS"
    if path and os.path.isfile(path):
        try:
            for m in OPTS_IN_SCRIPT.finditer(open(path, encoding="utf-8").read()):
                name = next(g for g in m.groups() if g)
                if name not in ("BRIDGE_OPTS",):
                    return name
        except OSError:
            pass
    return fallback


def build_code(code=None, file=None, opts=None, opts_name=None, print_result=False):
    lines = ["import json as _bridge_json"]
    if opts is not None:
        name = opts_name or default_opts_name(file)
        lines.append("%s = _bridge_json.loads(%r)" % (name, json.dumps(opts)))
    if file:
        src = open(file, encoding="utf-8").read()
        path = os.path.abspath(file)
        lines.append("__file__ = %r" % path)
    else:
        src, path = code, "<bridge>"
    lines.append("result = {}")
    lines.append("exec(compile(%r, %r, 'exec'), globals())" % (src, path))
    if print_result:
        lines.append("print(%r + _bridge_json.dumps(result, default=repr))" % RESULT_TAG)
    return "\n".join(lines) + "\n"


def parse_tagged(stdout, tag=None):
    """Last line `<TAG> {json}` (preferring `tag`), or the __BRIDGE_RESULT__ line."""
    best = None
    for line in stdout.splitlines():
        line = line.rstrip("\r")
        if line.startswith(RESULT_TAG):
            try:
                best = (RESULT_TAG, json.loads(line[len(RESULT_TAG):]))
            except ValueError:
                pass
            continue
        m = re.match(r"^([A-Z][A-Z0-9_]+) (\{.*\}|\[.*\])\s*$", line)
        if m:
            try:
                val = json.loads(m.group(2))
            except ValueError:
                continue
            if tag is None or m.group(1) == tag or best is None or best[0] != tag:
                best = (m.group(1), val)
    return best


def exec_on(host, port, protocol, code, timeout, probe_timeout=3.0):
    t0 = time.monotonic()
    if protocol == "auto":
        pr = probe_protocol(host, port, probe_timeout)
        protocol = pr["protocol"]
        if protocol not in ("official", "blender-mcp"):
            return {"ok": False, "port": port, "protocol": protocol, "probe": pr,
                    "error": "no Blender bridge on this port"}
    try:
        if protocol == "official":
            resp = send_official(host, port, code, timeout=timeout)
            ok = resp.get("status") == "ok"
            out = {"ok": ok, "protocol": protocol, "result": resp.get("result"), "stdout": resp.get("stdout", ""),
                   "stderr": resp.get("stderr", "")}
            if not ok:
                out["error"] = resp.get("message")
        else:
            resp = send_blender_mcp(host, port, "execute_code", {"code": code}, timeout=timeout)
            ok = resp.get("status") == "success"
            stdout = (resp.get("result") or {}).get("result", "") if ok else ""
            tagged = parse_tagged(stdout or "")
            clean = "\n".join(l for l in (stdout or "").splitlines() if not l.startswith(RESULT_TAG))
            out = {"ok": ok, "protocol": protocol, "result": tagged[1] if tagged and tagged[0] == RESULT_TAG else None,
                   "stdout": clean}
            if not ok:
                out["error"] = resp.get("message")
    except (OSError, TimeoutError, ValueError) as ex:
        out = {"ok": False, "protocol": protocol, "error": "%s: %s" % (type(ex).__name__, ex)}
        if isinstance(ex, TimeoutError):
            out["hint"] = "run `detect` on this port; the other protocol hangs silently"
    out["port"] = port
    out["elapsed_s"] = round(time.monotonic() - t0, 3)
    return out


# ---------------------------------------------------------------- executables
def _version_from_path(p):
    m = re.search(r"[Bb]lender[ -]?(\d+\.\d+)", p)
    return m.group(1) if m else None


def find_blenders(run_version=False):
    cands = []
    for var in ("BLENDER_PATH", "BLENDER_EXE", "BLENDER"):
        if os.environ.get(var):
            cands.append(os.environ[var])
    w = shutil.which("blender")
    if w:
        cands.append(w)
    sysname = platform.system()
    home = os.path.expanduser("~")
    if sysname == "Windows":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            cands += glob.glob(os.path.join(root, "Blender Foundation", "Blender*", "blender.exe"))
            cands += glob.glob(os.path.join(root, "Steam", "steamapps", "common", "Blender", "blender.exe"))
        cands += glob.glob(os.path.join(home, "AppData", "Local", "Programs", "Blender Foundation", "Blender*",
                                        "blender.exe"))
    elif sysname == "Darwin":
        for root in ("/Applications", os.path.join(home, "Applications")):
            cands += glob.glob(os.path.join(root, "Blender*.app", "Contents", "MacOS", "Blender"))
    else:
        cands += ["/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender",
                  "/var/lib/flatpak/exports/bin/org.blender.Blender"]
        cands += glob.glob("/opt/blender*/blender") + glob.glob(os.path.join(home, "blender*", "blender"))
    seen, out = set(), []
    for c in cands:
        if not c or not os.path.isfile(c):
            continue
        key = os.path.normcase(os.path.realpath(c))
        if key in seen:
            continue
        seen.add(key)
        item = {"path": c, "version": _version_from_path(c)}
        if run_version:
            try:
                r = subprocess.run([c, "-b", "--factory-startup", "--version"], capture_output=True, text=True,
                                   timeout=30)
                m = re.search(r"Blender (\d+\.\d+(?:\.\d+)?)", r.stdout)
                item["version"] = m.group(1) if m else item["version"]
            except (OSError, subprocess.TimeoutExpired) as ex:
                item["error"] = str(ex)
        out.append(item)

    def vkey(i):
        try:
            return tuple(int(x) for x in (i["version"] or "0").split("."))
        except ValueError:
            return (0,)
    return sorted(out, key=vkey, reverse=True)


def classify_tools(names):
    stripped = {re.split(r"__|:", n.strip())[-1] for n in names if n.strip()}
    hits = {k: sorted(stripped & v) for k, v in TOOL_SIGNATURES.items()}
    kind = max(hits, key=lambda k: len(hits[k])) if any(hits.values()) else (
        "generic-exec" if {"execute_blender_code", "execute_code"} & stripped else None)
    return {"bridge": kind, "matched": hits, "has_exec": bool({"execute_blender_code", "execute_code"} & stripped)}


# ---------------------------------------------------------------- commands
def cmd_detect(a):
    t0 = time.monotonic()
    ports = [int(p) for p in a.ports.split(",")] if a.ports else list(DEFAULT_PORTS)
    for var in ("BLENDER_MCP_PORT", "BLENDER_PORT"):
        if os.environ.get(var, "").isdigit() and int(os.environ[var]) not in ports:
            ports.append(int(os.environ[var]))
    bridges = []
    for port in ports:
        pr = probe_protocol(a.host, port, a.timeout)
        if pr["protocol"] in ("official", "blender-mcp"):
            code = build_code(PROBE_CODE, print_result=pr["protocol"] == "blender-mcp")
            info = exec_on(a.host, port, pr["protocol"], code, timeout=max(a.timeout, 5.0))
            if info.get("ok"):
                pr["session"] = info.get("result")
            else:
                pr["session_error"] = info.get("error")
            pr["capabilities"] = CAPABILITIES[pr["protocol"]]
        bridges.append(pr)
    exes = [] if a.no_exe else find_blenders(a.exe_version)
    tools = classify_tools(a.tools.split(",")) if a.tools else None
    live = [b for b in bridges if b.get("session")]
    if tools and tools["has_exec"]:
        rec = "use the listed MCP tools (%s); scripts via exec of file text + <NAME>_OPTS" % tools["bridge"]
    elif live:
        b = live[0]
        ui = not b["session"].get("background") and b["session"].get("view3d_areas", 0) > 0
        rec = "socket %s on port %d (%s): bridge_client.py exec --port %d" % (
            b["protocol"], b["port"], "live UI" if ui else "background, no UI context", b["port"])
    elif exes:
        rec = "headless only: bridge_client.py run-cli --blender \"%s\"" % exes[0]["path"]
    else:
        rec = "no Blender found: ask the user for the executable path or to enable the MCP add-on"
    data = {"cmd": "detect", "bridges": bridges, "executables": exes, "tools": tools, "recommended": rec,
            "cli_capabilities": CAPABILITIES["cli"], "elapsed_s": round(time.monotonic() - t0, 3)}
    return emit(data, ok=bool(live or exes or (tools and tools["has_exec"])))


def _load_opts(a):
    if a.opts_file:
        return json.load(open(a.opts_file, encoding="utf-8"))
    if a.opts:
        return json.loads(a.opts)
    return None


def cmd_exec(a):
    if not (a.code or a.file):
        return emit({"cmd": "exec", "ok": False, "error": "--code or --file required"}, ok=False)
    opts = _load_opts(a)
    proto = a.protocol
    if proto == "auto":
        pr = probe_protocol(a.host, a.port, a.probe_timeout)
        if pr["protocol"] not in ("official", "blender-mcp"):
            return emit({"cmd": "exec", "ok": False, "probe": pr, "error": "no Blender bridge on port %d" % a.port},
                        ok=False)
        proto = pr["protocol"]
    code = build_code(a.code, a.file, opts, a.opts_name, print_result=proto == "blender-mcp")
    res = exec_on(a.host, a.port, proto, code, a.timeout)
    res["cmd"] = "exec"
    return emit(res, ok=res["ok"])


def cmd_run_cli(a, script_args):
    blender = a.blender or next((e["path"] for e in find_blenders()), None)
    if not blender:
        return emit({"cmd": "run-cli", "ok": False, "error": "no Blender executable; pass --blender"}, ok=False)
    argv = [blender, "-b"]
    if a.factory_startup:
        argv.append("--factory-startup")
    if a.blend:
        argv.append(a.blend)
    tag = None
    if a.script:
        argv += ["--python", a.script, "--"] + script_args
        tag = os.path.splitext(os.path.basename(a.script))[0].upper()
    elif a.code or a.file:
        argv += ["--python-expr", build_code(a.code, a.file, _load_opts(a), a.opts_name, print_result=True)]
    else:
        return emit({"cmd": "run-cli", "ok": False, "error": "--script, --code or --file required"}, ok=False)
    t0 = time.monotonic()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=a.timeout)
    except subprocess.TimeoutExpired:
        return emit({"cmd": "run-cli", "ok": False, "error": "timed out after %ss" % a.timeout}, ok=False)
    found = parse_tagged(p.stdout, tag)
    err_lines = [l for l in (p.stdout + "\n" + p.stderr).splitlines()
                 if "Error" in l or "Traceback" in l or l.startswith("  File")]
    out = {"cmd": "run-cli", "ok": found is not None and p.returncode == 0, "returncode": p.returncode,
           "tag": found[0] if found else None, "result": found[1] if found else None,
           "elapsed_s": round(time.monotonic() - t0, 2), "blender": blender}
    if err_lines:
        out["errors"] = err_lines[-12:]
    if not found:
        out["stdout_tail"] = p.stdout.splitlines()[-15:]
    return emit(out, ok=out["ok"])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    script_args = []
    if "--" in argv:
        i = argv.index("--")
        argv, script_args = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--host", default="localhost")
    d.add_argument("--ports", default="")
    d.add_argument("--timeout", type=float, default=3.0, help="per-port probe budget (s)")
    d.add_argument("--tools", default="", help="comma list of MCP tool names visible to the agent")
    d.add_argument("--no-exe", action="store_true")
    d.add_argument("--exe-version", action="store_true", help="run each blender --version (slow)")
    for name in ("exec", "run-cli"):
        s = sub.add_parser(name)
        s.add_argument("--code")
        s.add_argument("--file")
        s.add_argument("--opts")
        s.add_argument("--opts-file")
        s.add_argument("--opts-name")
        if name == "exec":
            s.add_argument("--host", default="localhost")
            s.add_argument("--port", type=int, default=9876)
            s.add_argument("--protocol", choices=["auto", "official", "blender-mcp"], default="auto")
            s.add_argument("--timeout", type=float, default=120.0)
            s.add_argument("--probe-timeout", type=float, default=3.0)
        else:
            s.add_argument("--script")
            s.add_argument("--blender")
            s.add_argument("--blend")
            s.add_argument("--factory-startup", action="store_true")
            s.add_argument("--timeout", type=float, default=600.0)
    a = ap.parse_args(argv)
    if a.cmd == "detect":
        return cmd_detect(a)
    if a.cmd == "exec":
        return cmd_exec(a)
    return cmd_run_cli(a, script_args)


if __name__ == "__main__":
    sys.exit(main())
