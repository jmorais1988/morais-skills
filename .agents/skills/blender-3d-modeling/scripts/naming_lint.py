"""Naming & file-hygiene lint for the open .blend: role prefixes by object type, material prefixes, default names
(`Cube`, `Material`), illegal characters/spaces, `.001` duplicate suffixes, L/R side suffixes (`.L/.R` canonical,
unpaired sides), `_LOD<n>` form, engine prefixes leaking into the working file, orphan data, non-relative external
paths, missing images/caches/libraries and missing linked data-blocks. Optional `--fix` applies only safe renames.

Headless / CLI (prints one line: NAMING_LINT <json>):
    blender -b scene.blend --python naming_lint.py -- [--profile working|archviz|game_export] [--rules rules.json]
        [--fix] [--relative] [--purge-orphans] [--save | --save-as PATH] [--strict] [--max-issues 300]
Live (Blender:execute_blender_code): set before exec
    NAMING_OPTS = {"profile": "working", "fix": False}   -> `result` dict
Without NAMING_OPTS the file only defines lint(), apply_fixes() and DEFAULT_RULES.

Rules: DEFAULT_RULES below; `--rules` JSON is deep-merged over them (e.g. {"profiles": {"working": {"type_roles":
{"ARMATURE": ["RIG", "ARM"]}}}, "severity": {"orphan_data": "warning"}}). Profiles:
  working     objects <ROLE>_<Name> (LIGHT->LGT_, CAMERA->CAM_, ARMATURE->RIG_, others any UPPER role), materials MAT_,
              engine prefixes (SM_/SK_ objects, M_/MI_ materials, T_ images) flagged: they belong in the export copy
  archviz     working + MESH roles limited to WALL/SLAB/FLR/CEIL/OPN/CUT/FRAME/GLASS/DOOR/WIN/FURN/GEO/REF
  game_export MESH SM_/SK_/UCX_/UBX_/USP_/UCP_, materials M_/MI_, images T_<Asset>_<Map>
Safe fixes (--fix): illegal chars/spaces -> '_', `.001` suffix -> base name (or base_02.. if taken), data-block
name = object name for single-user object data. --relative runs file.make_paths_relative (saved file only; a
path on another drive stays absolute). --purge-orphans runs a recursive local orphan purge (data loss: opt-in).
Nothing is renamed on linked data, bones (vertex groups / external retargets depend on them) or names that would
collide. Save with --save/--save-as or changes are lost when Blender exits.
Limitations: role/prefix rules are naming heuristics, not semantics; L/R detection is suffix-based (`_L`, `-R`,
`Left` ...) and can flag words that merely end in L/R when the separator matches; UDIM/sequence images are
checked by tile/first-frame file existence only.
"""
import bpy, os, re, sys, json, copy

TAG = "NAMING_LINT"

DEFAULT_RULES = {
    "legal_name": r"^[A-Za-z0-9_.\-]+$",
    "role_regex": r"^([A-Z][A-Z0-9]{1,7})_[A-Za-z0-9]",
    "default_names": ["Cube", "Plane", "Sphere", "Icosphere", "Cylinder", "Cone", "Torus", "Suzanne", "Grid", "Circle",
                      "Empty", "Camera", "Light", "Point", "Sun", "Spot", "Area", "Armature", "BezierCurve",
                      "BezierCircle", "NurbsPath", "NurbsCurve", "Text", "Mball", "Lattice", "Material", "Collection",
                      "Untitled", "Image", "Mesh", "Object", "Bone", "GeometryNodes", "NodeGroup", "Action"],
    "engine_prefixes": {"objects": ["SM_", "SK_"], "materials": ["M_", "MI_"], "images": ["T_"]},
    "lod_regex": r"_LOD\d+$",
    "lr_alternate_regex": r"(?:[_\-. ](?:L|R|l|r|Left|Right|left|right|LEFT|RIGHT)|(?:Left|Right))$",
    "lr_canonical_regex": r"\.(L|R)$",
    "check_types": ["objects", "materials", "meshes", "curves", "armatures", "cameras", "lights", "collections",
                    "images", "node_groups", "actions", "textures", "worlds", "scenes", "cache_files"],
    "orphan_types": ["meshes", "materials", "images", "textures", "node_groups", "actions", "curves", "armatures",
                     "cameras", "lights", "worlds", "cache_files", "grease_pencils_v3", "pointclouds", "volumes"],
    "path_types": ["images", "libraries", "cache_files", "sounds", "movieclips", "fonts", "volumes"],
    "ignore_names": ["Scene", "World", "Render Result", "Viewer Node", "Dots Stroke", "Bfont Regular", "Bfont"],
    "image_map_tokens": ["BaseColor", "Albedo", "Diffuse", "Color", "Normal", "N", "Roughness", "R", "Metallic", "M",
                         "AO", "ORM", "ARM", "MRA", "Height", "H", "Displacement", "Disp", "Emissive", "E", "Opacity",
                         "Alpha", "Mask", "Specular", "Gloss", "Subsurface", "Curvature", "Cavity", "ID", "D"],
    "severity": {"illegal_chars": "error", "missing_library": "error", "missing_linked_id": "error",
                 "missing_file": "error", "dup_suffix": "warning", "default_name": "warning",
                 "object_prefix": "warning", "role_not_allowed": "warning", "material_prefix": "warning",
                 "image_pattern": "warning", "engine_prefix_in_working": "warning", "lod_suffix": "warning",
                 "lr_convention": "warning", "lr_unpaired": "warning", "absolute_path": "warning",
                 "orphan_data": "info", "data_name": "info", "file_name": "warning", "unsaved_file": "info"},
    "profiles": {
        "working": {"material_prefixes": ["MAT_"], "flag_engine_prefixes": True, "image_pattern": None,
                    "type_roles": {"LIGHT": ["LGT"], "CAMERA": ["CAM"], "ARMATURE": ["RIG"], "MESH": None,
                                   "EMPTY": None, "CURVE": None, "CURVES": None, "GREASEPENCIL": None,
                                   "FONT": None, "LATTICE": None, "POINTCLOUD": None, "VOLUME": None,
                                   "LIGHT_PROBE": None, "SPEAKER": None, "META": None, "SURFACE": None}},
        "archviz": {"inherit": "working",
                    "type_roles": {"MESH": ["WALL", "SLAB", "FLR", "CEIL", "OPN", "CUT", "FRAME", "GLASS", "DOOR",
                                            "WIN", "FURN", "GEO", "REF"]}},
        "game_export": {"material_prefixes": ["M_", "MI_"], "flag_engine_prefixes": False,
                        "image_pattern": r"^T_[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*_(?P<map>[A-Za-z0-9]+)$",
                        "type_roles": {"MESH": ["SM", "SK", "UCX", "UBX", "USP", "UCP"], "EMPTY": ["SOCKET"],
                                       "ARMATURE": None, "LIGHT": None, "CAMERA": None}},
    },
}


# ------------------------------------------------------------------ rules
def _deep_merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def load_rules(rules=None, profile="working"):
    if isinstance(rules, str) and rules:
        with open(bpy.path.abspath(rules), encoding="utf-8") as fh:
            rules = json.load(fh)
    r = _deep_merge(DEFAULT_RULES, rules or {})
    profs = r["profiles"]
    if profile not in profs:
        raise ValueError(f"profile {profile!r} not in {sorted(profs)}")
    p, chain = {}, []
    name = profile
    while name:
        chain.append(profs[name]); name = profs[name].get("inherit")
    for layer in reversed(chain):
        p = _deep_merge(p, {k: v for k, v in layer.items() if k != "inherit"})
    r["profile"] = p
    r["profile_name"] = profile
    return r


# ------------------------------------------------------------------ helpers
_DUP = re.compile(r"^(.*)\.(\d{3,})$")


def _base(name):
    m = _DUP.match(name)
    return m.group(1) if m else name


def _abs(path, lib=None):
    try:
        return os.path.normpath(bpy.path.abspath(path, library=lib))
    except TypeError:
        return os.path.normpath(bpy.path.abspath(path))


def _coll(tname):
    return getattr(bpy.data, tname, None)


def _free_name(coll, want, current=None):
    if want not in coll or coll.get(want) is current:
        return want
    for i in range(2, 1000):
        cand = f"{want}_{i:02d}"
        if cand not in coll:
            return cand
    return None


def _sanitize(name, legal):
    s = re.sub(r"[^A-Za-z0-9_.\-]+", "_", name)
    s = re.sub(r"_{2,}", "_", s).strip("_")
    return s if s and re.match(legal, s) else None


def _image_files(img):
    """Candidate on-disk paths for a file-backed image -> (paths, mode)."""
    p = _abs(img.filepath, img.library)
    if img.source == 'TILED' and "<UDIM>" in p:
        return [p.replace("<UDIM>", str(t.number)) for t in img.tiles], "all"
    if img.source == 'TILED' and "<UVTILE>" in p:
        return [p.replace("<UVTILE>", f"u{(t.number - 1001) % 10 + 1}_v{(t.number - 1001) // 10 + 1}") for t in img.tiles], "all"
    return [p], "all"


class _Report:
    def __init__(self, rules):
        self.rules, self.issues = rules, []

    def add(self, rule, id_type, name, detail=None, fixable=False, library=None):
        self.issues.append({"rule": rule, "severity": self.rules["severity"].get(rule, "warning"), "type": id_type,
                            "name": name, "detail": detail, "fixable": bool(fixable),
                            **({"library": library} if library else {})})


# ------------------------------------------------------------------ lint
def lint(profile="working", rules=None):
    R = rules if isinstance(rules, dict) and "profile" in rules else load_rules(rules, profile)
    P = R["profile"]
    rep = _Report(R)
    legal = re.compile(R["legal_name"])
    role_re = re.compile(R["role_regex"])
    defaults = set(R["default_names"])
    ignore = set(R["ignore_names"])
    lod_ok = re.compile(R["lod_regex"])
    lod_any = re.compile(r"(?i)(?:^|[_\-. ])lod\d*(?:$|[_\-. ])")

    # --- generic name hygiene on every local data-block type
    for tname in R["check_types"]:
        coll = _coll(tname)
        if coll is None:
            continue
        for idb in coll:
            if idb.library is not None or idb.name in ignore or getattr(idb, "is_runtime_data", False):
                continue
            if tname == "images" and idb.type in ('RENDER_RESULT', 'COMPOSITING'):
                continue
            n = idb.name
            if not legal.match(n):
                rep.add("illegal_chars", tname, n, "allowed: A-Z a-z 0-9 _ . -", fixable=_sanitize(_base(n), R["legal_name"]) is not None)
            if _DUP.match(n) and tname != "scenes":
                rep.add("dup_suffix", tname, n, f"base {_base(n)!r}" + (" (taken)" if _base(n) in coll else " (free)"), fixable=True)
            if tname in ("objects", "materials", "collections") and _base(n) in defaults:
                rep.add("default_name", tname, n, "rename to <ROLE>_<Name>")
            if tname in ("objects", "meshes", "collections") and lod_any.search(_base(n)) and not lod_ok.search(_base(n)):
                rep.add("lod_suffix", tname, n, "use _LOD0.._LODn at the end of the name")

    # --- objects: role prefixes by type, engine prefixes, data names, L/R
    engine = R["engine_prefixes"]
    troles = P.get("type_roles", {})
    for o in bpy.data.objects:
        if o.library is not None:
            continue
        n = _base(o.name)
        eng = next((e for e in engine.get("objects", []) if n.startswith(e)), None)
        if eng and P.get("flag_engine_prefixes"):
            rep.add("engine_prefix_in_working", "objects", o.name, f"{eng} is applied in the export copy")
        m = role_re.match(n)
        allowed = troles.get(o.type)
        if not m and not eng:
            if n not in defaults:  # default names already reported
                rep.add("object_prefix", "objects", o.name, f"{o.type}: expected <ROLE>_<Name>" + (f" with role in {allowed}" if allowed else ""))
        elif allowed is not None:
            role = m.group(1) if m else eng.rstrip("_")
            if role not in allowed:
                rep.add("role_not_allowed", "objects", o.name, f"{o.type} role {role!r} not in {allowed}")
        d = o.data
        if d is not None and d.library is None and d.users == 1 and d.name != o.name and not o.name.startswith(("UCX_", "UBX_", "USP_", "UCP_")):
            rep.add("data_name", type(d).__name__, d.name, f"object {o.name!r}", fixable=True)

    # --- materials
    mpref = tuple(P.get("material_prefixes") or ())
    for mat in bpy.data.materials:
        if mat.library is not None or mat.name in ignore or mat.is_grease_pencil:
            continue
        n = _base(mat.name)
        eng = next((e for e in engine.get("materials", []) if n.startswith(e)), None)
        if eng and P.get("flag_engine_prefixes") and not n.startswith(mpref):
            rep.add("engine_prefix_in_working", "materials", mat.name, f"{eng} is applied in the export copy")
        elif mpref and not n.startswith(mpref):
            rep.add("material_prefix", "materials", mat.name, f"expected prefix {list(mpref)}")

    # --- images
    ipat = P.get("image_pattern")
    for img in bpy.data.images:
        if img.library is not None or img.type in ('RENDER_RESULT', 'COMPOSITING') or img.name in ignore:
            continue
        n = os.path.splitext(_base(img.name))[0]
        if ipat:
            m = re.match(ipat, n)
            if not m:
                rep.add("image_pattern", "images", img.name, "expected T_<Asset>_<Map>")
            elif m.groupdict().get("map") and m.group("map") not in R["image_map_tokens"]:
                rep.add("image_pattern", "images", img.name, f"map token {m.group('map')!r} not in image_map_tokens")
        elif P.get("flag_engine_prefixes") and any(n.startswith(e) for e in engine.get("images", [])):
            rep.add("engine_prefix_in_working", "images", img.name, "T_ is applied in the export copy")

    # --- L/R suffixes: objects + bones per armature
    alt = re.compile(R["lr_alternate_regex"])
    canon = re.compile(R["lr_canonical_regex"])

    def _lr(names, id_type, owner=None):
        names = [_base(x) for x in names]
        s = set(names)
        for x in names:
            label = f"{owner}/{x}" if owner else x
            mc = canon.search(x)
            if mc:
                other = x[:-1] + ("R" if mc.group(1) == "L" else "L")
                if other not in s:
                    rep.add("lr_unpaired", id_type, label, f"no {other!r}")
            elif alt.search(x) and not re.search(r"_LOD\d+$", x):
                rep.add("lr_convention", id_type, label, "use .L/.R (mirror tools, symmetrize and exporters key on it)")

    _lr([o.name for o in bpy.data.objects if o.library is None], "objects")
    for arm in bpy.data.armatures:
        if arm.library is None:
            _lr([b.name for b in arm.bones], "bones", arm.name)
            for b in arm.bones:
                if not legal.match(b.name):
                    rep.add("illegal_chars", "bones", f"{arm.name}/{b.name}", "not auto-fixed (vertex groups depend on bone names)")

    # --- orphans
    for tname in R["orphan_types"]:
        coll = _coll(tname)
        if coll is None:
            continue
        for idb in coll:
            if idb.library is None and idb.users == 0 and not idb.use_fake_user and idb.name not in ignore:
                if tname == "images" and idb.type in ('RENDER_RESULT', 'COMPOSITING'):
                    continue
                rep.add("orphan_data", tname, idb.name, "0 users, no fake user: not written on save (5.x)")

    # --- external paths: relative + existence
    saved = bool(bpy.data.filepath)
    if not saved:
        rep.add("unsaved_file", "file", "", "relative-path checks need a saved file")
    for lib in bpy.data.libraries:
        if getattr(lib, "is_archive", False):
            continue  # 5.0+ archive libraries hold packed linked IDs
        p = _abs(lib.filepath, lib.parent)
        if lib.is_missing or not os.path.isfile(p):
            rep.add("missing_library", "libraries", lib.name, {"filepath": lib.filepath, "resolved": p})
        if saved and not lib.filepath.startswith("//"):
            rep.add("absolute_path", "libraries", lib.name, lib.filepath, fixable=True)
    for tname in ("images", "cache_files", "sounds", "movieclips", "fonts", "volumes"):
        coll = _coll(tname)
        if coll is None or tname not in R["path_types"]:
            continue
        for idb in coll:
            fp = getattr(idb, "filepath", "")
            if not fp or fp.startswith("<builtin>"):
                continue
            if tname == "images" and (idb.source not in ('FILE', 'SEQUENCE', 'MOVIE', 'TILED') or idb.packed_file):
                continue
            if getattr(idb, "packed_file", None):
                continue
            libname = idb.library.name if idb.library else None
            paths = _image_files(idb)[0] if tname == "images" else [_abs(fp, idb.library)]
            miss = [q for q in paths if not os.path.exists(q)]
            if miss:
                rep.add("missing_file", tname, idb.name, {"filepath": fp, "missing": miss[:8]}, library=libname)
            if saved and idb.library is None and not fp.startswith("//"):
                rep.add("absolute_path", tname, idb.name, fp, fixable=True)
    for tname in ("objects", "collections", "meshes", "materials", "node_groups", "images", "actions", "armatures"):
        for idb in _coll(tname):
            if idb.library is not None and getattr(idb, "is_missing", False):
                rep.add("missing_linked_id", tname, idb.name, "placeholder: library or data-block missing", library=idb.library.name)

    # --- file name
    if saved:
        fn = os.path.basename(bpy.data.filepath)
        stem = os.path.splitext(fn)[0]
        if not re.match(r"^[A-Za-z0-9_\-]+$", stem):
            rep.add("file_name", "file", fn, "use letters, digits, _ and - only (no spaces)")

    counts = {"error": 0, "warning": 0, "info": 0}
    by_rule = {}
    for i in rep.issues:
        counts[i["severity"]] = counts.get(i["severity"], 0) + 1
        by_rule[i["rule"]] = by_rule.get(i["rule"], 0) + 1
    ver = re.search(r"_v(\d{3,})$", os.path.splitext(os.path.basename(bpy.data.filepath))[0]) if saved else None
    return {"blender": bpy.app.version_string, "file": bpy.data.filepath or None, "profile": R["profile_name"],
            "version_suffix": ver.group(0)[1:] if ver else None, "counts": counts, "by_rule": by_rule,
            "fixable": sum(1 for i in rep.issues if i["fixable"]), "issues": rep.issues}


# ------------------------------------------------------------------ fixes
_DATA_COLLS = ("meshes", "curves", "armatures", "cameras", "lights", "lattices", "metaballs", "grease_pencils_v3",
                "pointclouds", "volumes", "speakers", "lightprobes")


def _data_coll(d):
    for t in _DATA_COLLS:
        c = _coll(t)
        if c is not None and c.get(d.name) is d:
            return c
    return None


def _sync_data_name(o, done, skipped):
    d = o.data
    if d is None or d.library is not None or d.users != 1 or d.name == o.name:
        return
    c = _data_coll(d)
    if c is None:
        return
    if o.name in c and c.get(o.name) is not d:
        skipped.append({"type": "data", "name": d.name, "why": f"{o.name!r} already used by another data-block"}); return
    old = d.name; d.name = o.name
    done.append({"fix": "data_name", "from": old, "to": d.name})


def apply_fixes(issues, rules, renames=True, relative=False, purge_orphans=False):
    legal = rules["legal_name"]
    done, skipped = [], []
    todo = [i for i in issues if renames and i["fixable"] and i["rule"] in ("illegal_chars", "dup_suffix") and i["type"] != "bones"]
    todo.sort(key=lambda i: i["type"] != "objects")  # objects first: their data follows the new name
    seen = set()
    for i in todo:
        key = (i["type"], i["name"])
        if key in seen:
            continue
        seen.add(key)
        coll = _coll(i["type"])
        idb = coll.get(i["name"]) if coll is not None else None
        if idb is None:
            continue  # already renamed together with its object
        if idb.library is not None:
            skipped.append({"type": i["type"], "name": i["name"], "why": "linked"}); continue
        want = _sanitize(_base(idb.name), legal)
        new = _free_name(coll, want, idb) if want else None
        if new is None:
            skipped.append({"type": i["type"], "name": i["name"], "why": "no legal free name"}); continue
        if new != idb.name:
            old = idb.name
            idb.name = new
            done.append({"fix": "rename", "type": i["type"], "from": old, "to": idb.name})
            if i["type"] == "objects":
                d = idb.data
                if d is not None and d.name == old:
                    _sync_data_name(idb, done, skipped)
    if renames:
        for i in issues:
            if i["rule"] == "data_name" and i["fixable"]:
                o = next((o for o in bpy.data.objects if o.data is not None and o.data.name == i["name"]
                          and type(o.data).__name__ == i["type"]), None)
                if o is not None:
                    _sync_data_name(o, done, skipped)
    if relative:
        if bpy.data.filepath:
            r = bpy.ops.file.make_paths_relative()
            done.append({"fix": "make_paths_relative", "op": sorted(r)})
        else:
            skipped.append({"fix": "make_paths_relative", "why": "file never saved"})
    if purge_orphans:
        before = sum(len(getattr(bpy.data, t)) for t in rules["orphan_types"] if hasattr(bpy.data, t))
        try:
            bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
        except AttributeError:
            bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
        after = sum(len(getattr(bpy.data, t)) for t in rules["orphan_types"] if hasattr(bpy.data, t))
        done.append({"fix": "orphans_purge", "removed": before - after})
    return done, skipped


def run(profile="working", rules=None, fix=False, relative=False, purge_orphans=False, strict=False, max_issues=300,
        save=False, save_as=None):
    R = load_rules(rules, profile)
    res = lint(profile, R)
    if fix or relative or purge_orphans:
        before = {"counts": res["counts"], "by_rule": res["by_rule"]}
        done, skipped = apply_fixes(res["issues"], R, renames=fix, relative=relative, purge_orphans=purge_orphans)
        res = lint(profile, R)
        res["before_fix"] = before
        res["fixes"] = done
        res["fix_skipped"] = skipped
    res["pass"] = res["counts"]["error"] == 0 and (not strict or res["counts"]["warning"] == 0)
    if len(res["issues"]) > max_issues:
        res["issues_truncated"] = len(res["issues"]) - max_issues
        res["issues"] = res["issues"][:max_issues]
    if save_as:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(save_as)); res["saved"] = save_as
    elif save:
        if bpy.data.filepath:
            bpy.ops.wm.save_mainfile(); res["saved"] = bpy.data.filepath
        else:
            res["saved"] = None
    return res


def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="naming_lint.py")
    ap.add_argument("--profile", default="working"); ap.add_argument("--rules")
    ap.add_argument("--fix", action="store_true"); ap.add_argument("--relative", action="store_true")
    ap.add_argument("--purge-orphans", action="store_true"); ap.add_argument("--strict", action="store_true")
    ap.add_argument("--max-issues", type=int, default=300)
    ap.add_argument("--save", action="store_true"); ap.add_argument("--save-as")
    a = ap.parse_args(argv)
    return run(a.profile, a.rules, a.fix, a.relative, a.purge_orphans, a.strict, a.max_issues, a.save, a.save_as)


if "NAMING_OPTS" in globals():
    result = run(**NAMING_OPTS)
    print(TAG, json.dumps({k: result[k] for k in ("pass", "counts", "by_rule")}))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:])
    print(TAG, json.dumps(result, default=str))
else:
    result = {"defined": ["lint", "apply_fixes", "run", "load_rules", "DEFAULT_RULES"]}
