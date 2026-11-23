"""Phoneme/viseme timing -> shape-key lip-sync keys: centred attack/release crossfades, co-articulation (short sounds
don't reach full value), optional box smoothing, jaw and blink channels, optional sound strip -- then gates on the keys.

Headless / CLI (prints one line: LIPSYNC_KEYS <json>):
    blender -b head.blend --python lipsync_keys.py -- --object Head --timing cues.json [--set oculus|arkit|preston|rhubarb]
        [--source auto|arpabet|oculus|preston|rhubarb] [--prefix ""] [--map custom.json] [--offset 0] [--attack 2]
        [--release 3] [--smooth 0] [--intensity 1] [--last-hold 0.12] [--jaw jawOpen | --jaw-bone Rig:jaw --jaw-angle 18]
        [--blink eyeBlinkLeft,eyeBlinkRight --blink-every 4 --seed 1] [--audio line.wav --audio-channel 1]
        [--dat-fps 24] [--resolve-overlaps] [--allow-unknown] [--allow-missing] [--save out.blend]
Live (Blender:execute_blender_code): set before exec
    LIPSYNC_OPTS = {"object": "Head", "timing": "cues.json", "set": "oculus", "jaw": "jawOpen"}   -> `result` dict
Without LIPSYNC_OPTS the file only defines load_timing, resolve, build_lipsync and the tables.

Timing input (auto-detected; `timing` may also be a list/dict in Live use):
  * JSON list: [{"t": 0.12, "phoneme": "AA"}, ...]; keys t|time|start, phoneme|viseme|value|shape, optional end|dur, weight
  * Rhubarb Lip Sync JSON {"mouthCues": [{"start", "end", "value": "A".."H"|"X"}]} and TSV lines "0.05<TAB>D"
  * Moho switch .dat ("MohoSwitch1" header, "frame shape" lines, as written by Rhubarb/Papagayo) [unverified: frames
    treated as 1-based at --dat-fps]
Symbols: ARPAbet/CMU (stress digits stripped), Oculus visemes, Preston Blair or Rhubarb letters. Everything maps through
the 15 Oculus visemes; Rhubarb->Preston uses Rhubarb's own table; ARKit output is a heuristic blend per viseme.
Gates: every non-neutral segment >= 1 frame long reads >= 0.5 x its weight at its middle frame; no two exclusive visemes
> 0.9 on the same frame (ARKit: contradictory pairs such as pucker+stretch); all values in [0, 1]; the slot plays (the
shape key value after frame_set equals the F-curve); unknown symbols, overlapping input intervals and missing shape
keys are reported and fail unless allowed. Keys are written LINEAR on integer frames to action "<object>_Lipsync" (KEY
slot) on the mesh's shape-key datablock; existing curves for the same channels are replaced.
Limitations: no audio analysis -- get timings from Rhubarb/Papagayo/a forced aligner; mapping tables are conventions,
tune per character; jaw bone keys use rotation_euler X of a pose bone.
"""
import bpy, json, math, os, random, re, sys

OCULUS = ["sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "ih", "oh", "ou"]
PRESTON = ["AI", "E", "O", "U", "etc", "FV", "L", "MBP", "WQ", "rest"]
RHUBARB = ["A", "B", "C", "D", "E", "F", "G", "H", "X"]
NEUTRAL = {"sil", "rest", "X"}
ARPA_TO_OC = {"AA": "aa", "AE": "aa", "AH": "aa", "AO": "oh", "AW": "aa", "AY": "aa", "EH": "E", "ER": "RR", "EY": "E",
              "IH": "ih", "IY": "ih", "OW": "oh", "OY": "oh", "UH": "ou", "UW": "ou", "B": "PP", "M": "PP", "P": "PP",
              "F": "FF", "V": "FF", "TH": "TH", "DH": "TH", "T": "DD", "D": "DD", "K": "kk", "G": "kk", "NG": "kk",
              "CH": "CH", "JH": "CH", "SH": "CH", "ZH": "CH", "S": "SS", "Z": "SS", "N": "nn", "L": "nn", "R": "RR",
              "W": "ou", "Y": "ih", "HH": ("aa", 0.3), "SIL": "sil", "SP": "sil", "SPN": "sil", "": "sil"}
RH_TO_OC = {"A": "PP", "B": "SS", "C": "E", "D": "aa", "E": "oh", "F": "ou", "G": "FF", "H": "nn", "X": "sil"}
RH_TO_PB = {"A": "MBP", "B": "etc", "C": "E", "D": "AI", "E": "O", "F": "U", "G": "FV", "H": "L", "X": "rest"}  # Rhubarb README
PB_TO_OC = {"MBP": "PP", "FV": "FF", "etc": "DD", "AI": "aa", "E": "E", "O": "oh", "U": "ou", "WQ": "ou", "L": "nn",
            "rest": "sil"}
OC_TO_PB = {"sil": "rest", "PP": "MBP", "FF": "FV", "TH": "etc", "DD": "etc", "kk": "etc", "CH": "etc", "SS": "etc",
            "nn": "L", "RR": "etc", "aa": "AI", "E": "E", "ih": "E", "oh": "O", "ou": "U"}
OC_TO_RH = {"sil": "X", "PP": "A", "FF": "G", "TH": "B", "DD": "B", "kk": "B", "CH": "B", "SS": "B", "nn": "H", "RR": "B",
            "aa": "D", "E": "C", "ih": "B", "oh": "E", "ou": "F"}
OC_TO_ARKIT = {  # heuristic starting points; tune per face
    "sil": {}, "PP": {"mouthClose": 0.3, "mouthPressLeft": 0.6, "mouthPressRight": 0.6},
    "FF": {"mouthRollLower": 0.6, "mouthUpperUpLeft": 0.3, "mouthUpperUpRight": 0.3, "jawOpen": 0.05},
    "TH": {"jawOpen": 0.15, "tongueOut": 0.4}, "DD": {"jawOpen": 0.2}, "kk": {"jawOpen": 0.25},
    "CH": {"mouthFunnel": 0.5, "jawOpen": 0.15}, "SS": {"mouthStretchLeft": 0.4, "mouthStretchRight": 0.4, "jawOpen": 0.05},
    "nn": {"jawOpen": 0.15}, "RR": {"mouthPucker": 0.4, "jawOpen": 0.15}, "aa": {"jawOpen": 0.7},
    "E": {"jawOpen": 0.4, "mouthStretchLeft": 0.3, "mouthStretchRight": 0.3},
    "ih": {"jawOpen": 0.25, "mouthSmileLeft": 0.3, "mouthSmileRight": 0.3},
    "oh": {"jawOpen": 0.45, "mouthFunnel": 0.6}, "ou": {"mouthPucker": 0.8, "jawOpen": 0.15}}
ARKIT_EXCLUSIVE = [("mouthPucker", "mouthStretchLeft"), ("mouthPucker", "mouthStretchRight"), ("mouthPucker", "mouthSmileLeft"),
                   ("mouthPucker", "mouthSmileRight"), ("mouthFunnel", "mouthStretchLeft"), ("mouthFunnel", "mouthStretchRight")]
JAW_OPEN = {"sil": 0, "PP": 0, "FF": 0.1, "TH": 0.2, "DD": 0.25, "kk": 0.3, "CH": 0.2, "SS": 0.1, "nn": 0.2, "RR": 0.25,
            "aa": 0.8, "E": 0.5, "ih": 0.35, "oh": 0.6, "ou": 0.3}


def load_timing(timing, dat_fps=24.0):
    """-> (events [{t, end|None, sym, weight}], format, source hint or None)"""
    data, fmt, hint = timing, "list", None
    if isinstance(timing, str):
        with open(timing, encoding="utf-8-sig") as fh:
            text = fh.read()
        s = text.lstrip()
        if s.startswith("MohoSwitch"):
            ev = []
            for ln in s.splitlines()[1:]:
                parts = ln.split()
                if len(parts) >= 2:
                    ev.append({"t": (float(parts[0]) - 1) / dat_fps, "end": None, "sym": parts[1], "weight": 1.0})
            return ev, "moho_dat", None
        if s[:1] in "[{":
            data = json.loads(s)
        else:
            ev = []
            for ln in s.splitlines():
                parts = ln.strip().split()
                if len(parts) >= 2:
                    ev.append({"t": float(parts[0]), "end": None, "sym": parts[1], "weight": 1.0})
            return ev, "tsv", None
    if isinstance(data, dict) and "mouthCues" in data:
        return [{"t": float(c["start"]), "end": float(c["end"]), "sym": str(c["value"]), "weight": 1.0}
                for c in data["mouthCues"]], "rhubarb_json", "rhubarb"
    ev = []
    for it in data:
        t = float(next(it[k] for k in ("t", "time", "start") if k in it))
        sym = str(next((it[k] for k in ("phoneme", "viseme", "value", "shape") if k in it), ""))
        end = float(it["end"]) if "end" in it else (t + float(it["dur"]) if "dur" in it else None)
        ev.append({"t": t, "end": end, "sym": sym, "weight": float(it.get("weight", 1.0))})
    return ev, fmt, hint


def _detect_source(syms):
    s = set(syms)
    if s <= set(RHUBARB):
        return "rhubarb"
    if s <= set(OCULUS):
        return "oculus"
    if s <= set(PRESTON):
        return "preston"
    return "arpabet"


def _to_oculus(sym, source):
    if source == "oculus":
        return (sym, 1.0) if sym in OCULUS else None
    if source == "rhubarb":
        return (RH_TO_OC[sym], 1.0) if sym in RH_TO_OC else None
    if source == "preston":
        return (PB_TO_OC[sym], 1.0) if sym in PB_TO_OC else None
    v = ARPA_TO_OC.get(re.sub(r"\d$", "", sym.upper()))
    return None if v is None else (v if isinstance(v, tuple) else (v, 1.0))


def resolve(sym, source, target, custom=None):
    """-> (oculus viseme or None, [(channel, weight)]) ; channels empty for neutral; None oculus = unknown symbol."""
    if custom and sym in custom:
        m = custom[sym]
        return "custom", [(k, float(v)) for k, v in (m.items() if isinstance(m, dict) else [(m, 1.0)])]
    if source == "rhubarb" and target == "preston":
        if sym not in RH_TO_PB:
            return None, []
        return RH_TO_OC[sym], ([] if RH_TO_PB[sym] in NEUTRAL else [(RH_TO_PB[sym], 1.0)])
    oc = _to_oculus(sym, source)
    if oc is None:
        return None, []
    v, w = oc
    if source == "arpabet" and target == "preston" and re.sub(r"\d$", "", sym.upper()) == "W":
        return v, [("WQ", w)]
    if target == "oculus":
        ch = v
    elif target == "preston":
        ch = OC_TO_PB[v]
    elif target == "rhubarb":
        ch = OC_TO_RH[v]
    else:
        return v, [(k, x * w) for k, x in OC_TO_ARKIT[v].items()]
    return v, ([] if ch in NEUTRAL else [(ch, w)])


def _segments(events, source, target, custom, last_hold, resolve_overlaps):
    order = sorted(range(len(events)), key=lambda i: events[i]["t"])
    ev = [events[i] for i in order]
    unknown, overlaps, segs = {}, [], []
    for i, e in enumerate(ev):
        nxt = ev[i + 1]["t"] if i + 1 < len(ev) else None
        end = e["end"] if e["end"] is not None else (nxt if nxt is not None else e["t"] + last_hold)
        oc, chans = resolve(e["sym"], source, target, custom)
        if oc is None:
            unknown.setdefault(e["sym"], round(e["t"], 3))
        if nxt is not None and (end > nxt + 1e-6 or nxt - e["t"] < 1e-6) and e["sym"] != ev[i + 1]["sym"]:
            overlaps.append({"a": e["sym"], "b": ev[i + 1]["sym"], "t": round(e["t"], 3), "next_t": round(nxt, 3),
                             "overlap_s": round(end - nxt, 4)})
            if resolve_overlaps:
                end = max(e["t"], nxt)
        segs.append({"t": e["t"], "end": end, "sym": e["sym"], "oc": oc, "chans": chans, "w": e["weight"]})
    merged = []   # merge consecutive identical resolutions so a held viseme doesn't dip at event boundaries
    for s in segs:
        if merged and merged[-1]["chans"] == s["chans"] and merged[-1]["oc"] == s["oc"] and \
                abs(merged[-1]["end"] - s["t"]) < 1e-6 and merged[-1]["w"] == s["w"]:
            merged[-1]["end"] = s["end"]
        else:
            merged.append(dict(s))
    return merged, unknown, overlaps, order != list(range(len(events)))


def _env(f, s, e, a, r):
    return max(0.0, min(1.0, 0.5 + (f - s) / a, 0.5 + (e - f) / r))


def _box(vals, k):
    if k <= 1:
        return vals
    h = k // 2
    return [sum(vals[max(0, i - h):i + h + 1]) / len(vals[max(0, i - h):i + h + 1]) for i in range(len(vals))]


def _sparse(frames, vals, tol=1e-4):
    keep = [0]
    for i in range(1, len(vals) - 1):
        f0, f1 = frames[keep[-1]], frames[i + 1]
        lin = vals[keep[-1]] + (vals[i + 1] - vals[keep[-1]]) * (frames[i] - f0) / (f1 - f0)
        if abs(vals[i] - lin) > tol:
            keep.append(i)
    keep.append(len(vals) - 1)
    return [(frames[i], vals[i]) for i in keep]


def _channelbag(idb, action_name, id_type):
    act = bpy.data.actions.get(action_name) or bpy.data.actions.new(action_name)
    slot = next((s for s in act.slots if getattr(s, "target_id_type", None) == id_type), None) or \
        act.slots.new(id_type=id_type, name=idb.name)
    layer = act.layers[0] if len(act.layers) else act.layers.new("Layer")
    strip = layer.strips[0] if len(layer.strips) else layer.strips.new(type='KEYFRAME')
    ad = idb.animation_data_create()
    ad.action = act
    ad.action_slot = slot
    return act, slot, strip.channelbag(slot, ensure=True)


def _write(cb, path, keys, group, index=0):
    old = cb.fcurves.find(path, index=index)
    if old:
        cb.fcurves.remove(old)
    fc = cb.fcurves.ensure(path, index=index, group_name=group)
    fc.keyframe_points.add(len(keys))
    for kp, (f, v) in zip(fc.keyframe_points, keys):
        kp.co = (f, v)
        kp.interpolation = 'LINEAR'
    fc.update()
    return fc


def build_lipsync(object=None, timing=None, set="oculus", source="auto", prefix="", map=None, offset=0.0, attack=2.0,
                  release=3.0, smooth=0, intensity=1.0, last_hold=0.12, jaw=None, jaw_bone=None, jaw_angle=18.0,
                  blink=None, blink_every=4.0, seed=1, audio=None, audio_channel=1, dat_fps=24.0,
                  resolve_overlaps=False, allow_unknown=False, allow_missing=False, save=None):
    scn = bpy.context.scene
    obj = bpy.data.objects.get(object) if object else bpy.context.object
    if obj is None or obj.type != 'MESH' or not obj.data.shape_keys:
        return {"pass": False, "failed": ["object"], "reason": f"mesh with shape keys not found: {object}"}
    key = obj.data.shape_keys
    kb_names = {k.name: k.name for k in key.key_blocks}
    kb_lower = {k.name.lower(): k.name for k in key.key_blocks}
    custom = None
    if map:
        custom = json.load(open(map, encoding="utf-8")) if isinstance(map, str) else map
    events, fmt, hint = load_timing(timing, dat_fps)
    src = source if source != "auto" else (hint or _detect_source([e["sym"] for e in events]))
    fps = scn.render.fps / scn.render.fps_base
    segs, unknown, overlaps, unsorted = _segments(events, src, set, custom, last_hold, resolve_overlaps)
    fr = lambda t: scn.frame_start + t * fps + offset
    missing, chan_map = [], {}
    for s in segs:
        for ch, _ in s["chans"]:
            full = prefix + ch
            name = kb_names.get(full) or kb_lower.get(full.lower())
            if name:
                chan_map[ch] = name
            elif ch not in missing:
                missing.append(ch)
    if not segs:
        return {"pass": False, "failed": ["timing"], "reason": "no events"}
    f0 = int(math.floor(fr(segs[0]["t"]) - attack)) - 1
    f1 = int(math.ceil(fr(segs[-1]["end"]) + release)) + 1
    frames = list(range(f0, f1 + 1))
    curves = {}
    jaw_vals = [0.0] * len(frames)
    for s in segs:
        a_, b_ = fr(s["t"]), fr(s["end"])
        env = [_env(f, a_, b_, attack, release) * s["w"] * intensity for f in frames]
        for ch, w in s["chans"]:
            if ch in chan_map:
                cv = curves.setdefault(ch, [0.0] * len(frames))
                for i, v in enumerate(env):
                    cv[i] += v * w
        if s["oc"] in JAW_OPEN:
            for i, v in enumerate(env):
                jaw_vals[i] += v * JAW_OPEN[s["oc"]]
    for ch in curves:
        curves[ch] = [min(1.0, max(0.0, v)) for v in _box(curves[ch], int(smooth))]
    act, slot, cb = _channelbag(key, f"{obj.name}_Lipsync", 'KEY')
    for fc in [fc for fc in cb.fcurves if fc.group and fc.group.name in ("Visemes", "Jaw", "Blink")]:
        cb.fcurves.remove(fc)   # idempotent re-run: drop channels written by a previous timing file
    written = {}
    for ch, vals in curves.items():
        name = chan_map[ch]
        fc = _write(cb, f'key_blocks["{name}"].value', _sparse(frames, vals), "Visemes")
        written[name] = len(fc.keyframe_points)
    jaw_info = None
    jaw_vals = [min(1.0, v) for v in _box(jaw_vals, int(smooth))]
    if jaw and jaw not in written:
        jn = kb_names.get(jaw) or kb_lower.get(jaw.lower())
        if jn:
            fc = _write(cb, f'key_blocks["{jn}"].value', _sparse(frames, jaw_vals), "Jaw")
            written[jn] = len(fc.keyframe_points)
            jaw_info = {"shape_key": jn, "keys": len(fc.keyframe_points)}
        else:
            missing.append(jaw)
    elif jaw:
        jaw_info = {"shape_key": jaw, "note": "already driven by the viseme set; not overwritten"}
    if jaw_bone:
        rig_name, _, bone = jaw_bone.partition(":")
        rig = bpy.data.objects.get(rig_name)
        if rig and rig.type == 'ARMATURE' and bone in rig.pose.bones:
            rig.pose.bones[bone].rotation_mode = 'XYZ'
            _, _, rcb = _channelbag(rig, f"{rig.name}_Lipsync", 'OBJECT')
            ang = math.radians(jaw_angle)
            fc = _write(rcb, f'pose.bones["{bone}"].rotation_euler', [(f, v * ang) for f, v in _sparse(frames, jaw_vals)],
                        bone, index=0)
            jaw_info = {"bone": jaw_bone, "keys": len(fc.keyframe_points), "max_deg": round(max(jaw_vals) * jaw_angle, 2)}
        else:
            missing.append(jaw_bone)
    blinks = []
    if blink:
        names = [kb_names.get(b) or kb_lower.get(b.lower()) for b in (blink.split(",") if isinstance(blink, str) else blink)]
        if None in names:
            missing.append("blink")
        rng = random.Random(seed)
        t = blink_every * rng.uniform(0.25, 0.75)
        tend = segs[-1]["end"]
        while t < tend:
            blinks.append(round(fr(t)))
            t += blink_every * rng.uniform(0.7, 1.3)
        bk = [(frames[0], 0.0)]
        for b in blinks:
            bk += [(b, 0.0), (b + 2, 1.0), (b + 3, 1.0), (b + 7, 0.0)]
        for n in [n for n in names if n]:
            fc = _write(cb, f'key_blocks["{n}"].value', sorted(dict(bk).items()), "Blink")
            written[n] = len(fc.keyframe_points)
    strip = None
    if audio:
        se = scn.sequence_editor_create()
        old = se.strips.get(os.path.basename(audio))
        if old:
            se.strips.remove(old)
        st = se.strips.new_sound(os.path.basename(audio), audio, audio_channel, scn.frame_start)
        strip = {"name": st.name, "frame_start": st.frame_start, "duration": st.frame_final_duration}
    scn.frame_end = max(scn.frame_end, frames[-1], (strip["frame_start"] + strip["duration"]) if strip else 0)
    # ---- gates (read back from the written curves) ----
    fcs = {fc.data_path.split('"')[1]: fc for fc in cb.fcurves}
    val = lambda n, f: fcs[n].evaluate(f) if n in fcs else 0.0
    hits, checked, low = 0, 0, []
    for s in segs:
        a_, b_ = fr(s["t"]), fr(s["end"])
        if b_ - a_ < 1.0:
            continue
        for ch, w in s["chans"]:
            if ch not in chan_map or w * s["w"] * intensity < 0.2:
                continue
            checked += 1
            fm = round((a_ + b_) / 2)
            v = val(chan_map[ch], fm)
            if v >= 0.5 * min(1.0, w * s["w"] * intensity) - 1e-6:
                hits += 1
            elif len(low) < 10:
                low.append({"channel": chan_map[ch], "frame": fm, "value": round(v, 3), "sym": s["sym"]})
    if set == "arkit":
        pairs = [(a, b) for a, b in ARKIT_EXCLUSIVE if a in fcs and b in fcs]
    else:
        ex = [chan_map[c] for c in chan_map if c not in NEUTRAL]
        pairs = [(ex[i], ex[j]) for i in range(len(ex)) for j in range(i + 1, len(ex))]
    viol, nviol = [], 0
    for f in frames:
        for a, b in pairs:
            va, vb = val(a, f), val(b, f)
            if va > 0.9 and vb > 0.9:
                nviol += 1
                if len(viol) < 10:
                    viol.append({"frame": f, "a": a, "b": b, "values": [round(va, 3), round(vb, 3)]})
    rng_bad = [(n, round(kp.co[1], 4)) for n, fc in fcs.items() for kp in fc.keyframe_points
               if kp.co[1] < -1e-6 or kp.co[1] > 1 + 1e-6]
    plays = None
    if fcs:
        n0 = max(fcs, key=lambda n: max(kp.co[1] for kp in fcs[n].keyframe_points))
        fpk = max(fcs[n0].keyframe_points, key=lambda kp: kp.co[1]).co[0]
        scn.frame_set(int(fpk))
        plays = abs(key.key_blocks[n0].value - fcs[n0].evaluate(int(fpk))) < 1e-4
    failed = []
    if unknown and not allow_unknown:
        failed.append("unknown_symbols")
    if overlaps and not resolve_overlaps:
        failed.append("overlaps")
    if missing and not allow_missing:
        failed.append("missing_keys")
    if checked and hits < checked:
        failed.append("expected_frames")
    if nviol:
        failed.append("exclusive")
    if rng_bad:
        failed.append("range")
    if plays is False:
        failed.append("slot_plays")
    if save:
        bpy.ops.wm.save_as_mainfile(filepath=save, copy=True)
    return {"pass": not failed, "failed": failed, "object": obj.name, "format": fmt, "source": src, "set": set,
            "fps": fps, "frames": [frames[0], frames[-1]], "events": len(events), "segments": len(segs),
            "unsorted_input": unsorted, "unknown": unknown, "overlaps": overlaps[:10], "missing_keys": missing,
            "action": act.name, "slot": slot.identifier, "channels": written,
            "expected_frames": {"hit": hits, "checked": checked, "low": low},
            "exclusive": {"pairs": len(pairs), "violations": nviol, "first": viol}, "range_bad": rng_bad[:10],
            "slot_plays": plays, "jaw": jaw_info, "blinks": blinks, "audio": strip}


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="lipsync_keys.py")
    p.add_argument("--object"); p.add_argument("--timing", required=True)
    p.add_argument("--set", default="oculus", choices=["oculus", "arkit", "preston", "rhubarb"])
    p.add_argument("--source", default="auto", choices=["auto", "arpabet", "oculus", "preston", "rhubarb"])
    p.add_argument("--prefix", default=""); p.add_argument("--map"); p.add_argument("--offset", type=float, default=0.0)
    p.add_argument("--attack", type=float, default=2.0); p.add_argument("--release", type=float, default=3.0)
    p.add_argument("--smooth", type=int, default=0); p.add_argument("--intensity", type=float, default=1.0)
    p.add_argument("--last-hold", type=float, default=0.12); p.add_argument("--jaw"); p.add_argument("--jaw-bone")
    p.add_argument("--jaw-angle", type=float, default=18.0); p.add_argument("--blink")
    p.add_argument("--blink-every", type=float, default=4.0); p.add_argument("--seed", type=int, default=1)
    p.add_argument("--audio"); p.add_argument("--audio-channel", type=int, default=1)
    p.add_argument("--dat-fps", type=float, default=24.0); p.add_argument("--resolve-overlaps", action="store_true")
    p.add_argument("--allow-unknown", action="store_true"); p.add_argument("--allow-missing", action="store_true")
    p.add_argument("--save")
    a = vars(p.parse_args(argv))
    return build_lipsync(**a)


if "LIPSYNC_OPTS" in globals():
    result = build_lipsync(**LIPSYNC_OPTS); print(json.dumps({k: result.get(k) for k in ("pass", "failed", "channels")}))
elif __name__ == "__main__" and "--" in sys.argv:
    result = _cli(sys.argv[sys.argv.index("--") + 1:]); print("LIPSYNC_KEYS " + json.dumps(result, default=str))
else:
    result = {"defined": ["load_timing", "resolve", "build_lipsync"]}
