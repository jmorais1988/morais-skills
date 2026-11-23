#!/usr/bin/env python3
"""Measure a reference image instead of eyeballing it.

Usage:
    python measure_reference.py front.jpg [--grid 25] [--regions regions.json] [--bg auto|#rrggbb] [--tol 40] [--out-dir .]
                                          [--json]

Outputs (printed as JSON and saved next to the image unless --out-dir):
    <stem>_grid.png       the image with a labelled pixel grid overlaid — read landmark coordinates off it
    <stem>_mask.png       the foreground mask used for the bounding box (check it before trusting numbers)
    JSON: image size, foreground bbox, height/width, midline x, and per-region median RGB/hex
    --json                print exactly one line `MEASURE_REFERENCE <json>` (same data) instead of indented JSON,
                          for agents/bridge_client.parse_tagged; the default stays the human-readable form

regions.json (optional): {"receiver": [x0, y0, x1, y1], "skin": [x0, y0, x1, y1]}  in pixels.

Background detection: flood-fills from the four corners with a colour tolerance (`--tol`), so enclosed
dark areas (pupils, mouth recess) stay on the foreground side. Works for plain/studio backgrounds;
for busy photos crop the subject first or pass explicit regions and ignore the bbox.

Convert pixel readings to ratios of one reference dimension (total height, head height, overall length)
before writing them into NOTES.md. Watch for cast shadows and props at the bottom of the bbox — crop
the region you actually mean.
"""
import argparse, json, sys
from collections import deque
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("missing dependency: python -m pip install pillow")


def parse_hex(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def flood_background(im, tol, seed_color=None):
    w, h = im.size
    px = im.load()
    mask = bytearray(w * h)  # 1 = background
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    def close(c, ref):
        return abs(c[0]-ref[0]) + abs(c[1]-ref[1]) + abs(c[2]-ref[2]) <= tol * 3
    q = deque()
    for cx, cy in corners:
        ref = seed_color or px[cx, cy][:3]
        if close(px[cx, cy][:3], ref):
            q.append((cx, cy, ref)); mask[cy * w + cx] = 1
    while q:
        x, y, ref = q.popleft()
        for nx, ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
            if 0 <= nx < w and 0 <= ny < h:
                i = ny * w + nx
                if not mask[i] and close(px[nx, ny][:3], ref):
                    mask[i] = 1; q.append((nx, ny, ref))
    return mask


def bbox_from_mask(mask, w, h):
    xs, ys = [], []
    for y in range(h):
        row = y * w
        for x in range(w):
            if not mask[row + x]:
                xs.append(x); ys.append(y)
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def median_color(im, box):
    x0, y0, x1, y1 = box
    crop = im.crop((x0, y0, x1, y1)).convert("RGB")
    try:
        data = list(crop.get_flattened_data())
    except AttributeError:
        data = list(crop.getdata())
    if not data:
        return None
    chans = list(zip(*data))
    med = tuple(sorted(c)[len(c) // 2] for c in chans)
    return {"rgb": list(med), "hex": "#%02x%02x%02x" % med}


def draw_grid(im, step, bbox):
    out = im.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    w, h = out.size
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for x in range(0, w, step):
        major = (x // step) % 4 == 0
        d.line([(x, 0), (x, h)], fill=(255, 0, 0) if major else (255, 120, 120), width=1)
        if major: d.text((x + 2, 2), str(x), fill=(255, 0, 0), font=font)
    for y in range(0, h, step):
        major = (y // step) % 4 == 0
        d.line([(0, y), (w, y)], fill=(0, 120, 255) if major else (120, 170, 255), width=1)
        if major: d.text((2, y + 2), str(y), fill=(0, 120, 255), font=font)
    if bbox:
        d.rectangle(bbox, outline=(0, 255, 0), width=2)
        mx = (bbox[0] + bbox[2]) // 2
        d.line([(mx, bbox[1]), (mx, bbox[3])], fill=(0, 255, 0), width=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--grid", type=int, default=25, help="grid step in px (0 to skip)")
    ap.add_argument("--regions", help="JSON file: {name: [x0,y0,x1,y1]}")
    ap.add_argument("--bg", default="auto", help="'auto' (corner colours) or #rrggbb")
    ap.add_argument("--tol", type=int, default=40, help="per-channel colour tolerance for background")
    ap.add_argument("--out-dir")
    ap.add_argument("--json", action="store_true", help="print one line: MEASURE_REFERENCE <json>")
    a = ap.parse_args()

    src = Path(a.image); im = Image.open(src).convert("RGB"); w, h = im.size
    out_dir = Path(a.out_dir) if a.out_dir else src.parent
    seed = parse_hex(a.bg) if a.bg != "auto" else None
    mask = flood_background(im, a.tol, seed)
    bbox = bbox_from_mask(mask, w, h)

    result = {"image": str(src), "size": [w, h], "foreground_bbox": bbox}
    if bbox:
        bw, bh = bbox[2] - bbox[0] + 1, bbox[3] - bbox[1] + 1
        result.update({"fg_width_px": bw, "fg_height_px": bh, "fg_aspect_h_over_w": round(bh / bw, 3),
                       "midline_x": (bbox[0] + bbox[2]) / 2,
                       "note": "bbox includes cast shadows/props if they touch the subject — check the mask"})
    mimg = Image.frombytes("L", (w, h), bytes(255 if not m else 0 for m in mask))
    mimg.save(out_dir / f"{src.stem}_mask.png")
    if a.grid:
        draw_grid(im, a.grid, bbox).save(out_dir / f"{src.stem}_grid.png")
        result["grid_overlay"] = str(out_dir / f"{src.stem}_grid.png")
    if a.regions:
        regs = json.loads(Path(a.regions).read_text())
        result["regions"] = {k: median_color(im, v) for k, v in regs.items()}
    if a.json:
        print("MEASURE_REFERENCE " + json.dumps(result))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
