#!/usr/bin/env python3
"""Download reference images into an organized references/ folder.

Usage:
    python gather_references.py --out ./references --manifest urls.json [--asset "rifle"] [--sleep 0.3]

--sleep: seconds to wait between downloads (default 0.3). Raise it (1-2 s) for large batches or a single host so
the source isn't hammered; lower values risk HTTP 429 rate limiting.

urls.json is a list of entries:
    [{"url": "https://...jpg", "component": "01_receiver", "view": "side",
      "source": "wikimedia", "license": "CC-BY-SA", "generated": false,
      "notes": "optional"}]

`component` becomes a subfolder (use numbered prefixes: 00_overall, 01_..., 90_materials, 99_style).
`view` should be one of front|side|top|back|3q|closeup|cutaway|ortho|other.

Creates/updates:
    <out>/manifest.json      all entries with local file paths + sha1 (dedupes by hash)
    <out>/NOTES.md           template with a section per component (only created if missing)
    <out>/<component>/<component>_<view>_<nn>.<ext>

Requires: requests (`python -m pip install requests`). Pillow optional (`python -m pip install pillow`; verifies/normalizes images).
"""
import argparse, hashlib, json, os, re, sys, time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("missing dependency: python -m pip install requests")

try:
    from PIL import Image
except ImportError:
    Image = None

HEADERS = {"User-Agent": "Mozilla/5.0 (reference-gatherer; personal study use)"}
VIEWS = {"front", "side", "top", "back", "3q", "closeup", "cutaway", "ortho", "other"}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "item"


def download(url: str, timeout=30) -> bytes:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "image" not in ctype and not url.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        raise ValueError(f"not an image ({ctype})")
    return r.content


def normalize(data: bytes, dest_stem: Path) -> Path:
    """Save as png/jpg; convert webp/gif; return final path."""
    if Image is None:
        ext = ".jpg"
        p = dest_stem.with_suffix(ext); p.write_bytes(data); return p
    from io import BytesIO
    im = Image.open(BytesIO(data))
    im.load()
    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    if has_alpha:
        p = dest_stem.with_suffix(".png"); im.convert("RGBA").save(p, optimize=True)
    else:
        p = dest_stem.with_suffix(".jpg"); im.convert("RGB").save(p, quality=92)
    return p


def notes_template(asset: str, components) -> str:
    lines = [f"# Reference notes — {asset}", "",
             "Fill this in BEFORE modeling. Facts, ratios, decisions — not impressions.", "",
             "## Overall", "- Real dimensions (L × H × W, units, source):",
             "- Proportion anchors (ratios between major parts):",
             "- Silhouette landmarks (what reads at thumbnail size):",
             "- Symmetry / asymmetric parts:", "- Repeated elements (arrays, counts, pitch):",
             "- Target: use case / poly budget / deliverable:",
             "- Sensitivity ratios (check first):", "",
             "## Quality contract", "- Complexity tier (simple/moderate/complex/ultra):",
             "- Definition of done:", "- Required parts (macro/meso/micro) and repeat counts:",
             "- Required materials & local overrides:", "- Review views required:",
             "- Failure modes that block completion:", ""]
    for c in components:
        if c.startswith("00"):
            continue
        lines += [f"## {c}", "- Surface class (continuous-sculpt / assembled-solid / conforming-shell / surface-relief / fiber-strand / material-only):",
                  "- Character layer if applicable (L0..L6 / L-Void / L-Proxy):",
                  "- Shape / construction (primitive + operations):",
                  "- Dimensions & position relative to parent:",
                  "- Attachment: parent, socket, contact type (embedded/socket/overlap/hinge/surface), root→tip, embed depth:",
                  "- Details worth geometry vs texture-only:",
                  "- Material & edge treatment (bevel size):", ""]
    lines += ["## Deformation", "- Parts that move / bend / hinge → separate objects or loop requirements:", "",
              "## Comparison log", "- (stage) angle — discrepancies found → fix applied", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--manifest", required=True, help="JSON list of url entries")
    ap.add_argument("--asset", default="asset")
    ap.add_argument("--sleep", type=float, default=0.3)
    a = ap.parse_args()

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    entries = json.loads(Path(a.manifest).read_text())
    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"asset": a.asset, "items": []}
    seen_hashes = {i.get("sha1") for i in manifest["items"]}
    counters = {}
    for i in manifest["items"]:
        key = (i["component"], i["view"]); counters[key] = max(counters.get(key, 0), i.get("index", 0))

    ok = fail = dup = 0
    for e in entries:
        url = e["url"]; comp = slug(e.get("component", "00_overall"))
        view = e.get("view", "other"); view = view if view in VIEWS else "other"
        try:
            data = download(url)
        except Exception as ex:
            print(f"FAIL {url}: {ex}"); fail += 1; continue
        h = hashlib.sha1(data).hexdigest()
        if h in seen_hashes:
            print(f"DUP  {url}"); dup += 1; continue
        seen_hashes.add(h)
        counters[(comp, view)] = counters.get((comp, view), 0) + 1
        n = counters[(comp, view)]
        folder = out / comp; folder.mkdir(exist_ok=True)
        try:
            path = normalize(data, folder / f"{comp}_{view}_{n:02d}")
        except Exception as ex:
            print(f"FAIL {url}: bad image ({ex})"); fail += 1; continue
        item = {"file": str(path.relative_to(out)), "url": url, "component": comp, "view": view, "index": n,
                "source": e.get("source", ""), "license": e.get("license", "unknown — private study only"),
                "generated": bool(e.get("generated", False)), "notes": e.get("notes", ""), "sha1": h}
        if Image is not None:
            with Image.open(path) as im: item["size"] = list(im.size)
        manifest["items"].append(item); ok += 1
        print(f"OK   {item['file']}")
        time.sleep(a.sleep)

    mpath.write_text(json.dumps(manifest, indent=2))
    comps = sorted({i["component"] for i in manifest["items"]})
    notes = out / "NOTES.md"
    if not notes.exists():
        notes.write_text(notes_template(a.asset, comps))
        print(f"Wrote NOTES.md template — fill it in before modeling.")
    print(f"\n{ok} downloaded, {dup} duplicates skipped, {fail} failed. Manifest: {mpath}")
    print("Components:", ", ".join(comps))


if __name__ == "__main__":
    main()
