#!/usr/bin/env python3
"""Project state checklist for a modeling job — the checklist authority outside the conversation.

    project_state.py init  --state S.json --asset "Name" --profile <profile> [--budget-tris N] [--json]
    project_state.py next  --state S.json [--json]        # ordered steps, pending, loop counters; exit 3 on STOP
    project_state.py mark  <step> --state S.json --evidence <path> [--note "..."] [--json]
    project_state.py mark  <step> --state S.json --skip --reason "..." [--json]
    project_state.py loop  refine-plan|refine-geometry|request-input --state S.json --stage <step> [--note "..."] [--json]
    project_state.py add   <step> --state S.json [--after <step>] [--json]   # add a custom step
    project_state.py profiles [NAME] [--json]             # list the profiles with their step sequences

Profiles (24 — `profiles` prints each with its steps; PROFILES below is the source of truth):
    hard-surface, organic, character, archviz, animation, game-asset, jewelry, character-rig, uv-bake, stylized,
    simulation, product-render, mesh-repair, logo-solid, texture-paint, pipeline-publish, web-asset, print,
    environment, flora, fauna, city, modular-kit, kitbash

--json on any subcommand prints exactly one line `PROJECT_STATE <json>` instead of the human listing: the state
summary (asset, profile, budget_tris, steps [{id, status, evidence (count), note (last)}], done / pending / next,
corrections {total, max_total, per_stage, max_per_stage}, stop, all_done) plus the subcommand's own keys
(initialized, marked, loop, added, profiles). Usage errors print the same tag with an "error" key (exit 1);
argparse errors still go to stderr (exit 2). Exit codes are the same as the human mode (3 on STOP).
Rules encoded: every done step needs evidence; skipped needs a reason; corrections are counted per stage
(max 3) and per project (max 6) — hitting either prints STOP and exits 3: ask the user, don't continue.
Pure stdlib.
"""
import argparse, json, sys, time
from pathlib import Path

PROFILES = {
    "hard-surface": ["target", "references", "study-notes", "quality-contract", "blockout", "structure",
                     "bevel-shading", "detail", "topology-audit", "review-turntable", "materials", "uvs",
                     "cleanup", "export"],
    "organic": ["target", "references", "study-notes", "quality-contract", "blockout", "sculpt-primary",
                "sculpt-secondary", "retopology", "topology-audit", "detail-bake", "review-turntable",
                "materials", "uvs", "cleanup", "export"],
    "character": ["target", "references", "study-notes", "landmarks-measured", "quality-contract",
                  "layer-classification", "blockout", "voids-cut", "sculpt-primary", "sculpt-secondary",
                  "retopology", "topology-audit", "discrete-parts", "hair", "scalp-exposure", "rig",
                  "weights-check", "pose-sweep", "animation-check", "review-turntable", "materials", "uvs",
                  "cleanup", "export"],
    "archviz": ["target", "references", "study-notes", "quality-contract", "plan-typed", "shell-built", "shell-gates",
                "dimensions-verified", "detail-trims", "furniture-placed", "contact-dims-gates", "cameras", "lighting",
                "materials", "uv-scale", "exposure-render-settings", "zfight-glass-camera-gates", "review-shots",
                "cleanup", "export"],
    "animation": ["target", "references", "study-notes", "quality-contract", "rig-audit", "clip-list", "timing-chart",
                  "blocking-key-poses", "splining", "loop-check", "foot-contact-check", "shape-keys", "shapekey-check",
                  "review-playblast", "export-actions", "reimport-verify"],
    "game-asset": ["target", "references", "study-notes", "quality-contract", "budget", "blockout", "high-poly",
                   "low-poly", "uvs", "bake", "lods", "collision", "naming-export", "export-check", "engine-test"],
    "jewelry": ["target", "references", "size", "band", "stone", "seat", "head", "ring-gates", "shrink",
                "print-gate", "export-verified"],
    "character-rig": ["target", "references", "armature", "weights", "rig-check", "controls", "ik-check", "animate",
                      "bake-deform", "export-actions", "reimport-verify"],
    "uv-bake": ["target", "topology-final", "seams", "unwrap", "density", "pack", "uv-check", "bake",
                "rebuild-material", "export"],
    "stylized": ["target", "references", "study-notes", "style-decision", "quality-contract", "blockout",
                 "silhouette-review", "shapes-and-topology", "palette-and-shading", "face-normals", "outlines",
                 "lighting-rig", "review-shots", "cleanup", "export"],
    "simulation": ["target", "references", "study-notes", "quality-contract", "scale-and-transforms", "colliders-proxies",
                   "sim-setup", "preview-bake", "sim-gates", "final-bake", "apply-or-cache-export",
                   "render-or-delivery-check"],
    "product-render": ["target", "references", "quality-contract", "asset-check", "materials", "cameras-fitted",
                       "frame-margin-gate", "studio-lighting", "exposure", "glass-caustics", "test-render",
                       "turntable-loop-check", "passes-compositor", "farm-submit", "output-check", "review-shots",
                       "delivery"],
    "mesh-repair": ["target", "references", "intake-analyze", "scale-orientation", "repair-or-rebuild-decision",
                    "cleanup-repair", "deviation-gates", "retopo-or-decimate", "uvs", "texture-transfer-bake", "delight",
                    "topology-audit", "review-turntable", "provenance-license", "export"],
    "logo-solid": ["target", "references", "gather-svg", "import-scale", "join-fill", "extrude-bevel-clamp",
                   "convert-merge", "gates", "materials", "render-or-export"],
    "texture-paint": ["target", "references", "uv-check", "base-fill", "bake-guides", "paint", "save-images",
                      "bake-flatten", "export-check"],
    "pipeline-publish": ["naming-lint", "fix-names-paths", "domain-gates", "interchange-check", "library-report",
                         "increment-version-save", "publish-copy"],
    "web-asset": ["target", "references", "quality-contract", "budget", "model", "uvs", "bake-textures",
                  "gltf-materials", "compress", "export-check", "validator", "viewer-test"],
    "print": ["target", "references", "study-notes", "quality-contract", "process-and-units", "dimensions-verified",
              "blockout", "structure", "detail", "fits-clearances", "manifold-check", "wall-thickness",
              "review-turntable", "cleanup", "export-verified"],
    "environment": ["target", "references", "study-notes", "quality-contract", "scale-and-camera", "terrain-blockout",
                    "composition-review", "hero-assets", "modular-kit", "materials", "scatter", "atmosphere-lighting",
                    "performance-budget", "review-shots", "cleanup", "export"],
    "flora": ["target", "references", "study-notes", "quality-contract", "growth-structure", "trunk-branches",
              "leaves-cards", "materials", "variation-set", "wind", "lod", "review-turntable", "cleanup", "export"],
    "fauna": ["target", "references", "study-notes", "landmarks-measured", "quality-contract", "skeleton-reference",
              "blockout", "sculpt-primary", "sculpt-secondary", "retopology", "topology-audit", "rig",
              "weights-check", "pose-sweep", "fur-feathers-scales", "materials", "animation-check",
              "review-turntable", "uvs", "cleanup", "export"],
    "city": ["target", "references", "study-notes", "quality-contract", "scale-and-camera", "layout-roads-blocks",
             "greybox", "composition-review", "district-kits", "hero-buildings", "filler-generation", "dressing-props",
             "materials", "lod-hlod", "performance-budget", "review-shots", "cleanup", "export"],
    "modular-kit": ["target", "references", "study-notes", "quality-contract", "grid-spec", "piece-list",
                    "blockout-pieces", "sockets-validated", "stress-layouts", "detail", "trim-sheets-materials",
                    "uvs-lightmaps", "collision", "lods", "variants", "asset-library", "export", "export-check",
                    "engine-test"],
    "kitbash": ["target", "references", "study-notes", "quality-contract", "silhouette-blockout", "library-audit",
                "primary-parts", "secondary-parts", "tertiary-detail", "seams-shading", "review-turntable",
                "materials", "bake-or-merge", "cleanup", "export"],
}
MAX_PER_STAGE, MAX_TOTAL = 3, 6
TAG = "PROJECT_STATE "


def load(p):
    return json.loads(Path(p).read_text())


def save(p, s):
    s["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    Path(p).write_text(json.dumps(s, indent=2))


def emit(payload):
    print(TAG + json.dumps(payload, default=str))


def fail(a, msg):
    """usage error: JSON line + exit 1 in --json mode, plain stderr message (exit 1) otherwise."""
    if getattr(a, "json", False):
        emit({"command": a.cmd, "error": msg}); sys.exit(1)
    sys.exit(msg)


def loop_counts(s):
    per = {}
    for l in s["loops"]:
        per[l["stage"]] = per.get(l["stage"], 0) + 1
    return per, len(s["loops"])


def summary(s, command=None):
    """Machine-readable state summary (what `next` prints for humans)."""
    per, total = loop_counts(s)
    pending = [st["id"] for st in s["steps"] if st["status"] == "pending"]
    stopped = total >= MAX_TOTAL or any(v >= MAX_PER_STAGE for v in per.values())
    return {"command": command, "asset": s["asset"], "profile": s["profile"], "budget_tris": s.get("budget_tris"),
            "steps": [{"id": st["id"], "status": st["status"], "evidence": len(st["evidence"]),
                       "note": st["notes"][-1] if st["notes"] else None} for st in s["steps"]],
            "done": [st["id"] for st in s["steps"] if st["status"] == "done"], "pending": pending,
            "next": pending[0] if pending and not stopped else None,
            "corrections": {"total": total, "max_total": MAX_TOTAL, "per_stage": per, "max_per_stage": MAX_PER_STAGE},
            "stop": stopped, "all_done": not pending}


def cmd_init(a):
    if a.profile not in PROFILES: fail(a, f"unknown profile {a.profile}")
    steps = [{"id": s, "status": "pending", "evidence": [], "notes": []} for s in PROFILES[a.profile]]
    s = {"asset": a.asset, "profile": a.profile, "budget_tris": a.budget_tris, "steps": steps,
         "loops": [], "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    Path(a.state).parent.mkdir(parents=True, exist_ok=True)
    save(a.state, s)
    if not a.json: print(f"Initialized {a.state} ({a.profile}, {len(steps)} steps)")
    cmd_next(a, {"initialized": a.state, "step_count": len(steps)})


def cmd_next(a, extra=None):
    s = load(a.state)
    d = summary(s, a.cmd)
    if extra: d.update(extra)
    if a.json:
        emit(d)
        if d["stop"]: sys.exit(3)
        return
    per, total = loop_counts(s)
    print(f"Asset: {s['asset']}  profile: {s['profile']}  budget_tris: {s.get('budget_tris')}")
    for st in s["steps"]:
        mark = {"done": "x", "skipped": "-", "pending": " "}[st["status"]]
        extra_txt = f"  ({len(st['evidence'])} evidence)" if st["evidence"] else ""
        if st["status"] == "skipped": extra_txt = f"  (skipped: {st['notes'][-1] if st['notes'] else ''})"
        print(f"  [{mark}] {st['id']}{extra_txt}")
    print(f"Corrections: total {total}/{MAX_TOTAL}; per stage: {per or '{}'}")
    if d["stop"]:
        print("STOP: correction limit reached — report the remaining defects and ask the user how to proceed.")
        sys.exit(3)
    if d["pending"]:
        print(f"NEXT: {d['next']}")
    else:
        print("All steps done. Run final review + report.")


def cmd_mark(a):
    s = load(a.state)
    st = next((x for x in s["steps"] if x["id"] == a.step), None)
    if not st:
        fail(a, f"unknown step {a.step}; add it with `add`")
    if a.skip:
        if not a.reason: fail(a, "--skip requires --reason")
        st["status"] = "skipped"; st["notes"].append(a.reason)
    else:
        if not a.evidence: fail(a, "marking done requires --evidence <path> (screenshot, report json, notes section)")
        st["status"] = "done"; st["evidence"].append(a.evidence)
        if a.note: st["notes"].append(a.note)
    save(a.state, s)
    cmd_next(a, {"marked": a.step, "status": st["status"]})


def cmd_loop(a):
    s = load(a.state)
    rec = {"action": a.action, "stage": a.stage, "note": a.note or "", "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    s["loops"].append(rec)
    # reopen the stage so it must be re-verified with new evidence
    for st in s["steps"]:
        if st["id"] == a.stage and st["status"] == "done":
            st["status"] = "pending"; st["notes"].append(f"reopened by {a.action}")
    save(a.state, s)
    cmd_next(a, {"loop": rec})


def cmd_add(a):
    s = load(a.state)
    new = {"id": a.step, "status": "pending", "evidence": [], "notes": []}
    ids = [x["id"] for x in s["steps"]]
    if a.after and a.after in ids:
        s["steps"].insert(ids.index(a.after) + 1, new)
    else:
        s["steps"].append(new)
    save(a.state, s)
    cmd_next(a, {"added": a.step, "after": a.after if a.after in ids else None})


def cmd_profiles(a):
    if a.name and a.name not in PROFILES: fail(a, f"unknown profile {a.name}; known: {', '.join(PROFILES)}")
    names = [a.name] if a.name else list(PROFILES)
    if a.json:
        emit({"command": "profiles", "count": len(names), "profiles": {n: PROFILES[n] for n in names}}); return
    for n in names:
        print(f"{n} ({len(PROFILES[n])} steps): " + " > ".join(PROFILES[n]))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--state", required=True); p.add_argument("--asset", required=True)
    p.add_argument("--profile", choices=PROFILES.keys(), required=True); p.add_argument("--budget-tris", type=int)
    p = sub.add_parser("next"); p.add_argument("--state", required=True)
    p = sub.add_parser("mark"); p.add_argument("step"); p.add_argument("--state", required=True)
    p.add_argument("--evidence"); p.add_argument("--note"); p.add_argument("--skip", action="store_true"); p.add_argument("--reason")
    p = sub.add_parser("loop"); p.add_argument("action", choices=["refine-plan", "refine-geometry", "request-input"])
    p.add_argument("--state", required=True); p.add_argument("--stage", required=True); p.add_argument("--note")
    p = sub.add_parser("add"); p.add_argument("step"); p.add_argument("--state", required=True); p.add_argument("--after")
    p = sub.add_parser("profiles"); p.add_argument("name", nargs="?")
    for sp in sub.choices.values():
        sp.add_argument("--json", action="store_true", help="print one PROJECT_STATE <json> line instead of the listing")
    a = ap.parse_args()
    {"init": cmd_init, "next": cmd_next, "mark": cmd_mark, "loop": cmd_loop, "add": cmd_add, "profiles": cmd_profiles}[a.cmd](a)


if __name__ == "__main__":
    main()
