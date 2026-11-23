"""Command-line / farm rendering helper: build and run Blender background-render commands (chunks, parallel processes,
per-chunk logs), post-check an output folder (missing, zero-byte/placeholder, black, constant, transparent-empty and
identical-consecutive frames), read EXR headers (layers/channels, multi-part), and -- inside Blender -- enable render
passes, light groups and a compositor File Output node.

Pure Python (no bpy), prints one line: RENDER_CLI <json>
    python render_cli.py build --blender BLENDER --file scene.blend --out /abs/renders/shot_#### --start 1 --end 250
        [--frames 1,5,9 | --frames 1..20] [--engine CYCLES|BLENDER_EEVEE|BLENDER_WORKBENCH] [--device OPTIX|CUDA|HIP|ONEAPI|METAL|CPU]
        [--format PNG|OPEN_EXR|OPEN_EXR_MULTILAYER] [--scene NAME] [--threads 0] [--placeholders] [--no-overwrite]
        [--print-stats] [--chunks 4] [--node-index 0 --node-count 3] [--expr "python;statements"]
    python render_cli.py run  (same options) [--parallel 2] [--log-dir logs] [--timeout 0]
    python render_cli.py check --dir renders --pattern shot_####.png --start 1 --end 250 [--step 1]
        [--black 0.01] [--constant 0.004] [--max-decode-px 1000000] [--check-with-blender BLENDER]
    python render_cli.py exr-info file.exr [more.exr]
Inside Blender (bpy), prints RENDER_CLI <json>:
    BLENDER -b scene.blend --python render_cli.py -- passes --engine CYCLES --passes mist,ao,normal,depth,crypto_object,denoise
        [--lightgroups key=LGT_Key,fill=LGT_Fill] [--out //passes/shot_] [--no-multilayer] [--main-multilayer]
        [--view-layer ViewLayer] [--save out.blend]
    BLENDER -b --factory-startup --python render_cli.py -- stats --list files.json --json-out stats.json
Live (Blender:execute_blender_code): set before exec
    RENDER_CLI_OPTS = {"mode": "passes", "passes": ["mist", "crypto_object"], "lightgroups": {"key": ["LGT_Key"]},
                       "out": "//passes/shot_"}   -> `result` dict
Without RENDER_CLI_OPTS (and not run as a script) the file only defines functions.

Blender argument order matters (processed left to right): -b <file> first, then -S, --python-expr, -E, -o, -F, -x, -t,
then -s/-e/-a or -f; Cycles options after `--`. Frames are always rendered as an animation render from the command line.
Limitations: the pure-Python PNG decoder handles non-interlaced 8/16-bit PNGs; larger frames than --max-decode-px get a
compression-ratio heuristic (suspect_constant) -- use --check-with-blender for exact stats and for EXR/other formats.
"""
import json, os, re, sys, struct, zlib, time, hashlib, subprocess

TAG = "RENDER_CLI"


# ------------------------------------------------------------------------------------------------ command building
def parse_frames(spec):
    """'1,5,9' / '1..20' / '1..20,30' -> sorted unique list."""
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if ".." in part:
            a, b = part.split(".."); out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def split_chunks(frames=None, start=None, end=None, chunks=1):
    """Contiguous chunks. Returns list of dicts {"start","end"} for ranges or {"frames":[...]} for explicit lists."""
    chunks = max(1, int(chunks))
    if frames:
        k = max(1, -(-len(frames) // chunks))
        return [{"frames": frames[i:i + k]} for i in range(0, len(frames), k)]
    n = end - start + 1; k = max(1, -(-n // chunks))
    return [{"start": s, "end": min(end, s + k - 1)} for s in range(start, end + 1, k)]


def setup_expr(placeholders=False, no_overwrite=False, extra=None):
    stm = []
    if placeholders or no_overwrite:
        stm.append("r=bpy.context.scene.render")
    if placeholders:
        stm.append("r.use_placeholder=True")
    if no_overwrite:
        stm.append("r.use_overwrite=False")
    if extra:
        stm.append(extra)
    return ("import bpy;" + ";".join(stm)) if stm else None


def build_command(blender, file=None, out=None, start=None, end=None, frames=None, engine=None, device=None, fmt=None,
                  scene=None, threads=None, placeholders=False, no_overwrite=False, print_stats=False, expr=None,
                  factory_startup=False):
    cmd = [blender, "-b"]
    if factory_startup:
        cmd.append("--factory-startup")
    if file:
        cmd.append(file)
    if scene:
        cmd += ["-S", scene]
    e = setup_expr(placeholders, no_overwrite, expr)
    if e:
        cmd += ["--python-exit-code", "1", "--python-expr", e]
    if engine:
        cmd += ["-E", engine]
    if out:
        cmd += ["-o", out]
    if fmt:
        cmd += ["-F", fmt, "-x", "1"]
    if threads is not None:
        cmd += ["-t", str(threads)]
    if frames:
        cmd += ["-f", ",".join(str(f) for f in frames)]
    else:
        if start is not None:
            cmd += ["-s", str(start)]
        if end is not None:
            cmd += ["-e", str(end)]
        cmd.append("-a")
    tail = []
    if device:
        tail += ["--cycles-device", device]
    if print_stats:
        tail.append("--cycles-print-stats")
    if tail:
        cmd += ["--"] + tail
    return cmd


def plan(opts):
    frames = parse_frames(opts["frames"]) if opts.get("frames") else None
    if frames is None and (opts.get("start") is None or opts.get("end") is None):
        chunks = [{}]  # use the file's own frame range
    else:
        chunks = split_chunks(frames, opts.get("start"), opts.get("end"), opts.get("chunks") or 1)
    if opts.get("node_count"):
        nc, ni = int(opts["node_count"]), int(opts.get("node_index") or 0)
        chunks = split_chunks(frames, opts.get("start"), opts.get("end"), nc)
        chunks = [chunks[ni]] if ni < len(chunks) else []
    common = {k: opts.get(k) for k in ("file", "out", "engine", "device", "fmt", "scene", "threads", "placeholders",
                                        "no_overwrite", "print_stats", "expr", "factory_startup")}
    return [{"chunk": i, **c, "cmd": build_command(opts["blender"], start=c.get("start"), end=c.get("end"),
                                                   frames=c.get("frames"), **common)} for i, c in enumerate(chunks)]


# ------------------------------------------------------------------------------------------------------ running
SAVED_RE = re.compile(r"Saved:\s*'([^']+)'")
ERR_RE = re.compile(r"(Traceback|Error:|EXCEPTION|out of memory|CUDA error|OptiX error|Segmentation fault|Illegal address)", re.I)


def run_chunk(job, log_dir=None, timeout=None):
    t0 = time.time(); log_path = None
    try:
        p = subprocess.run(job["cmd"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout or None)
        text = p.stdout.decode("utf-8", "replace"); code = p.returncode
    except subprocess.TimeoutExpired as ex:
        text = (ex.stdout or b"").decode("utf-8", "replace") + "\n<<TIMEOUT>>"; code = -999
    except FileNotFoundError as ex:
        text = str(ex); code = -998
    if log_dir:
        os.makedirs(log_dir, exist_ok=True); log_path = os.path.join(log_dir, f"chunk_{job['chunk']:03d}.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(" ".join(job["cmd"]) + "\n\n" + text)
    saved = SAVED_RE.findall(text)
    errors = sorted({m.group(0) for m in ERR_RE.finditer(text)})
    return {"chunk": job["chunk"], "range": {k: job[k] for k in ("start", "end", "frames") if job.get(k) is not None},
            "exit_code": code, "seconds": round(time.time() - t0, 2), "saved_count": len(saved),
            "saved_last": saved[-1] if saved else None, "error_markers": errors, "log": log_path,
            "ok": code == 0 and not errors}


def run_jobs(jobs, parallel=1, log_dir=None, timeout=None):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, int(parallel))) as ex:
        results = list(ex.map(lambda j: run_chunk(j, log_dir, timeout), jobs))
    return {"chunks": results, "all_ok": all(r["ok"] for r in results),
            "saved_total": sum(r["saved_count"] for r in results)}


# --------------------------------------------------------------------------------------------------- image reading
def _paeth(a, b, c):
    p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def png_read(path, max_px=1_000_000):
    """Pure-Python PNG reader -> dict(width, height, channels, bit_depth, idat_ratio, stats|None, pixel_hash)."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, ihdr = 8, [], None
    while pos + 8 <= len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]; typ = data[pos + 4:pos + 8]; body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat.append(body)
        elif typ == b"IEND":
            break
    if ihdr is None:
        raise ValueError("no IHDR")
    w, h, bd, ct, _, _, interlace = ihdr
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]; comp = b"".join(idat)
    raw_size = h * (1 + (w * ch * bd + 7) // 8)
    info = {"width": w, "height": h, "channels": ch, "bit_depth": bd, "color_type": ct,
            "idat_ratio": round(len(comp) / max(1, raw_size), 6), "pixel_hash": hashlib.md5(comp).hexdigest(), "stats": None}
    if w * h > max_px or interlace or bd < 8:
        return info
    raw = zlib.decompress(comp); bpp = max(1, ch * bd // 8); stride = (w * ch * bd + 7) // 8
    prev = bytearray(stride); rows = bytearray(); i = 0
    for _ in range(h):
        f = raw[i]; line = bytearray(raw[i + 1:i + 1 + stride]); i += stride + 1
        if f == 1:
            for x in range(bpp, stride): line[x] = (line[x] + line[x - bpp]) & 255
        elif f == 2:
            for x in range(stride): line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride): line[x] = (line[x] + ((line[x - bpp] if x >= bpp else 0) + prev[x]) // 2) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0; c = prev[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + _paeth(a, prev[x], c)) & 255
        rows += line; prev = line
    if bd == 16:
        from array import array
        vals = array("H"); vals.frombytes(bytes(rows))
        if sys.byteorder == "little": vals.byteswap()
        scale = 65535.0
    else:
        vals = memoryview(bytes(rows)); scale = 255.0
    ccount = ch if ct in (0, 2, 3) else ch - 1
    mins = [min(vals[k::ch]) / scale for k in range(ccount)]; maxs = [max(vals[k::ch]) / scale for k in range(ccount)]
    means = [sum(vals[k::ch]) / (w * h) / scale for k in range(ccount)]
    alpha_max = (max(vals[ch - 1::ch]) / scale) if ccount < ch else None
    info["stats"] = {"min": mins, "max": maxs, "mean": means, "alpha_max": alpha_max}
    return info


def exr_info(path):
    """Parse OpenEXR header(s): multi-part flag, per-part name/type/channels/compression/dataWindow. Pure Python."""
    with open(path, "rb") as f:
        data = f.read(4 << 20)
    magic, ver = struct.unpack("<ii", data[:8])
    if magic != 20000630:
        raise ValueError("not an OpenEXR file")
    multipart = bool(ver & 0x1000); pos = 8; parts = []
    comp_names = ["NONE", "RLE", "ZIPS", "ZIP", "PIZ", "PXR24", "B44", "B44A", "DWAA", "DWAB", "HTJ2K"]

    def cstr(p):
        e = data.index(b"\0", p); return data[p:e].decode("latin-1"), e + 1
    while True:
        attrs = {}
        while data[pos] != 0:
            name, pos = cstr(pos); typ, pos = cstr(pos); size = struct.unpack("<i", data[pos:pos + 4])[0]; pos += 4
            val = data[pos:pos + size]; pos += size
            if typ == "chlist":
                chans, q = [], 0
                while val[q] != 0:
                    e = val.index(b"\0", q); cname = val[q:e].decode("latin-1"); q = e + 1
                    ptype = struct.unpack("<i", val[q:q + 4])[0]; q += 16
                    chans.append({"name": cname, "type": ["UINT", "HALF", "FLOAT"][ptype] if 0 <= ptype < 3 else ptype})
                attrs[name] = chans
            elif typ == "string":
                attrs[name] = val.decode("latin-1", "replace")
            elif typ == "compression":
                attrs[name] = comp_names[val[0]] if val[0] < len(comp_names) else val[0]
            elif typ == "box2i":
                attrs[name] = list(struct.unpack("<iiii", val))
        pos += 1
        parts.append({"name": attrs.get("name"), "type": attrs.get("type"), "compression": attrs.get("compression"),
                      "dataWindow": attrs.get("dataWindow"), "channels": [c["name"] for c in attrs.get("channels", [])],
                      "channel_types": sorted({str(c["type"]) for c in attrs.get("channels", [])})})
        if not multipart or data[pos] == 0:
            break
    layers = sorted({c.rsplit(".", 1)[0] if "." in c else "" for p in parts for c in p["channels"]}
                    | {p["name"] for p in parts if p["name"]})
    return {"file": path, "multipart": multipart, "part_count": len(parts), "layers": layers, "parts": parts}


# --------------------------------------------------------------------------------------------------- folder check
def expand_pattern(pattern, frame):
    m = list(re.finditer(r"#+", pattern))
    if m:
        g = m[-1]; return pattern[:g.start()] + str(frame).zfill(len(g.group(0))) + pattern[g.end():]
    root, ext = os.path.splitext(pattern)
    return f"{root}{frame:04d}{ext}"  # Blender appends 4-digit frame numbers when no '#' is given


def classify(stats, black=0.01, constant=0.004):
    if not stats:
        return []
    flags = []
    if max(stats["max"]) <= black:
        flags.append("black")
    if max(mx - mn for mx, mn in zip(stats["max"], stats["min"])) <= constant:
        flags.append("constant")
    if stats.get("alpha_max") is not None and stats["alpha_max"] <= 0.0:
        flags.append("transparent_empty")
    return flags


def check_folder(directory, pattern, start, end, step=1, black=0.01, constant=0.004, max_decode_px=1_000_000,
                 blender=None):
    frames = list(range(start, end + 1, step)); report = {"missing": [], "zero_byte": [], "unreadable": [], "black": [],
                                                           "constant": [], "transparent_empty": [], "suspect_constant": [],
                                                           "identical_to_previous": [], "frames": {}}
    present = []
    for f in frames:
        p = os.path.join(directory, expand_pattern(pattern, f))
        if not os.path.exists(p):
            report["missing"].append(f); continue
        if os.path.getsize(p) == 0:
            report["zero_byte"].append(f); continue  # placeholder left by a crashed/unfinished node, or failed write
        present.append((f, p))
    infos = {}
    for f, p in present:
        try:
            if p.lower().endswith(".png") and not blender:
                infos[f] = png_read(p, max_decode_px)
            elif p.lower().endswith(".exr"):
                infos[f] = {"exr": exr_info(p)}
            else:
                infos[f] = {}
        except Exception as ex:
            report["unreadable"].append(f); infos[f] = {"error": str(ex)}
    if blender and present:
        stats = blender_stats(blender, [p for _, p in present])
        for f, p in present:
            s = stats.get(p, {})
            if "error" in s:
                report["unreadable"].append(f)
            infos[f] = {**infos.get(f, {}), **s}
    prev_hash = None; prev_f = None
    for f, p in present:
        inf = infos.get(f, {})
        for flag in classify(inf.get("stats"), black, constant):
            report[flag].append(f)
        if inf.get("stats") is None and inf.get("idat_ratio") is not None and inf["idat_ratio"] < 0.002:
            report["suspect_constant"].append(f)
        h = inf.get("pixel_hash")
        if h and h == prev_hash and prev_f is not None:
            report["identical_to_previous"].append(f)
        prev_hash, prev_f = h, f
        report["frames"][f] = {k: v for k, v in inf.items() if k in ("width", "height", "stats", "idat_ratio", "error")}
    report["unreadable"] = sorted(set(report["unreadable"]))
    bad = [k for k in ("missing", "zero_byte", "unreadable", "black", "constant", "transparent_empty", "identical_to_previous")
           if report[k]]
    report.update({"checked": len(frames), "present": len(present), "problems": bad, "pass": not bad})
    if len(frames) > 40:
        report["frames"] = {"omitted": f"{len(frames)} frames"}
    return report


def blender_stats(blender, files):
    import tempfile
    tmp = tempfile.mkdtemp(prefix="render_cli_"); lst = os.path.join(tmp, "files.json"); out = os.path.join(tmp, "stats.json")
    json.dump(files, open(lst, "w"))
    cmd = [blender, "-b", "--factory-startup", "--python", os.path.abspath(__file__), "--", "stats", "--list", lst, "--json-out", out]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return json.load(open(out)) if os.path.exists(out) else {f: {"error": "blender stats failed"} for f in files}


# ---------------------------------------------------------------------------------------------------- bpy helpers
PASS_ATTRS = {  # short name -> (owner, attribute); owner 'vl' = ViewLayer, 'cy' = ViewLayer.cycles, 'ee' = ViewLayer.eevee
    "depth": ("vl", "use_pass_z"), "z": ("vl", "use_pass_z"), "mist": ("vl", "use_pass_mist"), "normal": ("vl", "use_pass_normal"),
    "position": ("vl", "use_pass_position"), "vector": ("vl", "use_pass_vector"), "uv": ("vl", "use_pass_uv"),
    "ao": ("vl", "use_pass_ambient_occlusion"), "object_index": ("vl", "use_pass_object_index"),
    "material_index": ("vl", "use_pass_material_index"), "emit": ("vl", "use_pass_emit"), "environment": ("vl", "use_pass_environment"),
    "shadow": ("vl", "use_pass_shadow"), "diffuse_direct": ("vl", "use_pass_diffuse_direct"),
    "diffuse_indirect": ("vl", "use_pass_diffuse_indirect"), "diffuse_color": ("vl", "use_pass_diffuse_color"),
    "glossy_direct": ("vl", "use_pass_glossy_direct"), "glossy_indirect": ("vl", "use_pass_glossy_indirect"),
    "glossy_color": ("vl", "use_pass_glossy_color"), "transmission_direct": ("vl", "use_pass_transmission_direct"),
    "transmission_indirect": ("vl", "use_pass_transmission_indirect"), "transmission_color": ("vl", "use_pass_transmission_color"),
    "crypto_object": ("vl", "use_pass_cryptomatte_object"), "crypto_material": ("vl", "use_pass_cryptomatte_material"),
    "crypto_asset": ("vl", "use_pass_cryptomatte_asset"), "denoise": ("cy", "denoising_store_passes"),
    "shadow_catcher": ("cy", "use_pass_shadow_catcher"), "volume_direct": ("cy", "use_pass_volume_direct"),
    "render_time": ("cy", "pass_render_time"), "bloom": ("ee", "use_pass_bloom"), "transparent": ("ee", "use_pass_transparent"),
}
_SOCKET_TO_ITEM = {"VALUE": "FLOAT", "RGBA": "RGBA", "VECTOR": "VECTOR"}


def setup_passes(passes=(), lightgroups=None, out="//passes/", multilayer=True, main_multilayer=False, view_layer=None,
                 exr_codec="ZIP", color_depth="32", node_name="FO_Passes", engine=None):
    """Enable passes/light groups on a view layer and wire every enabled Render Layers output into a File Output node
    (5.x: scene.compositing_node_group, NodeGroupOutput replaces Composite, file_output_items). Idempotent.
    Render Layers sockets exist only for passes the CURRENT engine supports -> pass `engine` (Workbench exposes Image/Depth
    only); requested passes that got no socket are reported in `no_socket`."""
    import bpy
    sc = bpy.context.scene; vl = sc.view_layers[view_layer] if view_layer else bpy.context.view_layer
    if engine:
        sc.render.engine = engine
    enabled, unknown = [], []
    for p in passes:
        owner, attr = PASS_ATTRS.get(p, (None, None))
        tgt = {"vl": vl, "cy": getattr(vl, "cycles", None), "ee": getattr(vl, "eevee", None)}.get(owner)
        if tgt is None or not hasattr(tgt, attr):
            unknown.append(p); continue
        setattr(tgt, attr, True); enabled.append(p)
    lg_made = {}
    for name, objs in (lightgroups or {}).items():
        if name not in vl.lightgroups:
            vl.lightgroups.add(name=name)
        for on in ([objs] if isinstance(objs, str) else objs):
            if on.lower() == "world" and sc.world:
                sc.world.lightgroup = name
            elif on in bpy.data.objects:
                bpy.data.objects[on].lightgroup = name
        lg_made[name] = objs
    tree = sc.compositing_node_group
    if tree is None:
        tree = bpy.data.node_groups.new("COMP_Passes", "CompositorNodeTree"); sc.compositing_node_group = tree
    rl = next((n for n in tree.nodes if n.bl_idname == "CompositorNodeRLayers" and n.layer == vl.name), None)
    if rl is None:
        rl = tree.nodes.new("CompositorNodeRLayers"); rl.layer = vl.name; rl.location = (-400, 0)
    if not any(i.in_out == 'OUTPUT' for i in tree.interface.items_tree if getattr(i, "item_type", "SOCKET") == 'SOCKET'):
        tree.interface.new_socket(name="Image", in_out='OUTPUT', socket_type='NodeSocketColor')
    go = next((n for n in tree.nodes if n.bl_idname == "NodeGroupOutput"), None)
    if go is None:
        go = tree.nodes.new("NodeGroupOutput"); go.location = (300, 200)
    if not go.inputs[0].is_linked:
        tree.links.new(rl.outputs["Image"], go.inputs[0])
    fo = tree.nodes.get(node_name)
    if fo is None:
        fo = tree.nodes.new("CompositorNodeOutputFile"); fo.name = fo.label = node_name; fo.location = (300, -200)
    d, fname = os.path.split(out)
    fo.directory = (d + "/") if d else "//"; fo.file_name = fname
    fmt = fo.format
    fmt.media_type = 'MULTI_LAYER_IMAGE' if multilayer else 'IMAGE'
    if not multilayer:
        fmt.file_format = 'OPEN_EXR'
    fmt.color_depth = color_depth
    if hasattr(fmt, "exr_codec"):
        fmt.exr_codec = exr_codec
    bpy.context.view_layer.update()
    fo.file_output_items.clear()
    items = []
    for s in rl.outputs:
        if not s.enabled or s.name == "Alpha":
            continue
        it = fo.file_output_items.new(_SOCKET_TO_ITEM.get(s.type, "RGBA"), s.name)
        tree.links.new(s, fo.inputs[it.name]); items.append(it.name)
    if main_multilayer:
        sc.render.image_settings.media_type = 'MULTI_LAYER_IMAGE'
    hint = {"depth": "Depth", "z": "Depth", "mist": "Mist", "normal": "Normal", "ao": "Ambient Occlusion", "position": "Position",
            "crypto_object": "CryptoObject00", "crypto_material": "CryptoMaterial00", "denoise": "Denoising Albedo",
            "vector": "Vector", "emit": "Emission", "shadow_catcher": "Shadow Catcher"}
    no_socket = [q for q in enabled if q in hint and hint[q] not in items]
    return {"view_layer": vl.name, "engine": sc.render.engine, "enabled": enabled, "unknown": unknown, "no_socket": no_socket,
            "lightgroups": lg_made,
            "compositor": tree.name, "file_output": fo.name, "directory": fo.directory, "file_name": fo.file_name,
            "media_type": fmt.media_type, "file_format": fmt.file_format, "items": items,
            "main_output_media_type": sc.render.image_settings.media_type}


def image_stats(files):
    import bpy, numpy as np
    out = {}
    for p in files:
        try:
            img = bpy.data.images.load(p, check_existing=False)
            w, h = img.size; ch = img.channels
            a = np.empty(w * h * ch, dtype=np.float32); img.pixels.foreach_get(a); a = a.reshape(-1, ch)
            cc = min(3, ch)
            out[p] = {"width": w, "height": h, "channels": ch, "type": img.type,
                      "stats": {"min": a[:, :cc].min(0).tolist(), "max": a[:, :cc].max(0).tolist(), "mean": a[:, :cc].mean(0).tolist(),
                                "alpha_max": float(a[:, 3].max()) if ch == 4 else None},
                      "pixel_hash": hashlib.md5(np.round(a, 5).tobytes()).hexdigest()}
            bpy.data.images.remove(img)
        except Exception as ex:
            out[p] = {"error": str(ex)}
    return out


# -------------------------------------------------------------------------------------------------------- drivers
def _common_args(p):
    p.add_argument("--blender", default=os.environ.get("BLENDER", "blender")); p.add_argument("--file")
    p.add_argument("--out"); p.add_argument("--start", type=int); p.add_argument("--end", type=int); p.add_argument("--frames")
    p.add_argument("--engine"); p.add_argument("--device"); p.add_argument("--format", dest="fmt"); p.add_argument("--scene")
    p.add_argument("--threads", type=int); p.add_argument("--placeholders", action="store_true")
    p.add_argument("--no-overwrite", action="store_true"); p.add_argument("--print-stats", action="store_true")
    p.add_argument("--chunks", type=int, default=1); p.add_argument("--node-index", type=int); p.add_argument("--node-count", type=int)
    p.add_argument("--expr"); p.add_argument("--factory-startup", action="store_true")


def main_python(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="render_cli.py"); sub = ap.add_subparsers(dest="mode", required=True)
    b = sub.add_parser("build"); _common_args(b)
    r = sub.add_parser("run"); _common_args(r); r.add_argument("--parallel", type=int, default=1)
    r.add_argument("--log-dir"); r.add_argument("--timeout", type=float, default=0)
    c = sub.add_parser("check"); c.add_argument("--dir", required=True); c.add_argument("--pattern", required=True)
    c.add_argument("--start", type=int, required=True); c.add_argument("--end", type=int, required=True)
    c.add_argument("--step", type=int, default=1); c.add_argument("--black", type=float, default=0.01)
    c.add_argument("--constant", type=float, default=0.004); c.add_argument("--max-decode-px", type=int, default=1_000_000)
    c.add_argument("--check-with-blender")
    e = sub.add_parser("exr-info"); e.add_argument("files", nargs="+")
    a = ap.parse_args(argv); o = vars(a)
    if a.mode == "build":
        return {"mode": "build", "jobs": plan(o)}
    if a.mode == "run":
        jobs = plan(o); res = run_jobs(jobs, a.parallel, a.log_dir, a.timeout)
        return {"mode": "run", "commands": [" ".join(j["cmd"]) for j in jobs], **res}
    if a.mode == "check":
        return {"mode": "check", **check_folder(a.dir, a.pattern, a.start, a.end, a.step, a.black, a.constant,
                                                a.max_decode_px, a.check_with_blender)}
    if a.mode == "exr-info":
        return {"mode": "exr-info", "files": [exr_info(f) for f in a.files]}


def main_blender(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="render_cli.py (bpy)"); sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("passes"); p.add_argument("--passes", default=""); p.add_argument("--lightgroups", default="")
    p.add_argument("--out", default="//passes/"); p.add_argument("--no-multilayer", action="store_true")
    p.add_argument("--main-multilayer", action="store_true"); p.add_argument("--view-layer"); p.add_argument("--save")
    p.add_argument("--engine", help="set first: pass sockets depend on the engine (CYCLES, BLENDER_EEVEE)")
    s = sub.add_parser("stats"); s.add_argument("--list", required=True); s.add_argument("--json-out", required=True)
    a = ap.parse_args(argv)
    if a.mode == "stats":
        res = image_stats(json.load(open(a.list))); json.dump(res, open(a.json_out, "w")); return {"mode": "stats", "files": len(res)}
    lg = {}
    for item in filter(None, a.lightgroups.split(",")):
        k, _, v = item.partition("="); lg.setdefault(k, []).extend(filter(None, v.split("+")))
    res = setup_passes([x for x in a.passes.split(",") if x], lg, a.out, not a.no_multilayer, a.main_multilayer, a.view_layer,
                       engine=a.engine)
    if a.save:
        import bpy
        bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(a.save)); res["saved"] = a.save
    return {"mode": "passes", **res}


def _in_blender():
    try:
        import bpy  # noqa: F401
        return True
    except ImportError:
        return False


if "RENDER_CLI_OPTS" in globals():
    _o = dict(RENDER_CLI_OPTS); _m = _o.pop("mode", "passes")
    result = setup_passes(**_o) if _m == "passes" else image_stats(_o["files"])
    print(TAG + " " + json.dumps(result, default=str))
elif __name__ == "__main__" and _in_blender() and "--" in sys.argv:
    result = main_blender(sys.argv[sys.argv.index("--") + 1:])
    print(TAG + " " + json.dumps(result, default=str))
elif __name__ == "__main__" and not _in_blender():
    result = main_python(sys.argv[1:])
    print(TAG + " " + json.dumps(result, default=str))
else:
    result = {"defined": ["parse_frames", "split_chunks", "build_command", "plan", "run_jobs", "png_read", "exr_info",
                          "check_folder", "setup_passes", "image_stats", "PASS_ATTRS"]}
