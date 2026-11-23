#!/usr/bin/env python3
"""Compare a render against a reference image: aligned silhouette IoU, proportion, symmetry parity,
and interior appearance difference banded by height. ADVISORY — it measures outline and tone, not 3D form.

    python silhouette_compare.py --reference ref.png --render render.png --out cmp.png [--bands 8] [--tol 40] [--grid 48]
                                 [--json]
    --json: print exactly one line `SILHOUETTE_COMPARE <json>` (same data; on failure {"error": ...} and exit 1)
    instead of the indented JSON, for agents/bridge_client.parse_tagged. Default stays the human-readable form.

Both images are foreground-masked by corner flood fill (plain backgrounds expected; for photos on busy
backgrounds pre-crop or pre-mask). The render mask is scaled and translated to the reference mask's bounding
box before comparing, so framing differences don't dominate. Output JSON + a side-by-side sheet:
reference | render (aligned) | overlay (green = both, red = ref only, blue = render only).

Interpretation (see quality-gates.md): IoU uses only outline cells (~11 % of the figure) — a model with its
face deleted can score identically to the finished face. `interior_diff` bands compare luma inside the shared
silhouette, top to bottom; a band with large difference is where to look. Never optimize toward these numbers
against a photograph; use them to locate discrepancies, then judge with your eyes and the turntable.
"""
import argparse, json, sys
from collections import deque
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageChops
except ImportError:
    sys.exit("missing dependency: python -m pip install pillow")


def _data(im):
    try:
        return list(im.get_flattened_data())
    except AttributeError:
        return list(im.getdata())


def fg_mask(im, tol):
    im = im.convert("RGB"); w, h = im.size; px = im.load()
    mask = bytearray(w * h)
    def close(c, r): return abs(c[0]-r[0]) + abs(c[1]-r[1]) + abs(c[2]-r[2]) <= tol * 3
    q = deque()
    for cx, cy in [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)]:
        ref = px[cx, cy]
        if not mask[cy*w+cx]:
            mask[cy*w+cx] = 1; q.append((cx, cy, ref))
    while q:
        x, y, ref = q.popleft()
        for nx, ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
            if 0 <= nx < w and 0 <= ny < h and not mask[ny*w+nx] and close(px[nx, ny], ref):
                mask[ny*w+nx] = 1; q.append((nx, ny, ref))
    m = Image.frombytes("L", (w, h), bytes(0 if v else 255 for v in mask))
    return m


def bbox(m):
    return m.getbbox()


def align(render_img, render_mask, ref_box, size):
    """Scale+translate render so its mask bbox matches ref bbox; return (img, mask) on ref-size canvas."""
    rb = bbox(render_mask)
    if not rb: return None, None
    rw, rh = rb[2]-rb[0], rb[3]-rb[1]; tw, th = ref_box[2]-ref_box[0], ref_box[3]-ref_box[1]
    s = min(tw / rw, th / rh)
    nw, nh = max(1, int(rw*s)), max(1, int(rh*s))
    crop_img = render_img.convert("RGB").crop(rb).resize((nw, nh), Image.LANCZOS)
    crop_msk = render_mask.crop(rb).resize((nw, nh), Image.NEAREST)
    canvas_img = Image.new("RGB", size, (0, 0, 0)); canvas_msk = Image.new("L", size, 0)
    ox = ref_box[0] + (tw - nw)//2; oy = ref_box[1] + (th - nh)//2
    canvas_img.paste(crop_img, (ox, oy)); canvas_msk.paste(crop_msk, (ox, oy))
    return canvas_img, canvas_msk


def iou(a, b):
    inter = ImageChops.multiply(a, b); union = ImageChops.lighter(a, b)
    ia = sum(1 for v in _data(inter) if v) ; ua = sum(1 for v in _data(union) if v)
    return ia / ua if ua else 0.0, ia


def symmetry_parity(m):
    """Fraction of mask matching its horizontal mirror about the bbox midline."""
    b = bbox(m)
    if not b: return None
    crop = m.crop(b); flipped = crop.transpose(Image.FLIP_LEFT_RIGHT)
    same = sum(1 for x, y in zip(_data(crop), _data(flipped)) if (x > 0) == (y > 0))
    return round(same / (crop.size[0] * crop.size[1]), 3)


def interior_bands(ref_img, ren_img, shared_mask, bands, grid):
    """Mean |luma difference| inside the shared silhouette, per horizontal band, on a coarse grid."""
    b = bbox(shared_mask)
    if not b: return []
    ref_l = ref_img.convert("L"); ren_l = ren_img.convert("L"); mk = shared_mask
    x0, y0, x1, y1 = b; bh = (y1 - y0) / bands
    cw = max(1, (x1 - x0) // grid); ch = max(1, int(bh) // 4 or 1)
    out = []
    for i in range(bands):
        by0, by1 = int(y0 + i*bh), int(y0 + (i+1)*bh)
        cells, diffs = 0, 0.0
        for cy in range(by0, by1, ch):
            for cx in range(x0, x1, cw):
                box = (cx, cy, min(cx+cw, x1), min(cy+ch, by1))
                if mk.crop(box).getbbox() is None: continue
                # only cells mostly inside the silhouette
                cov = sum(1 for v in _data(mk.crop(box)) if v) / ((box[2]-box[0])*(box[3]-box[1]))
                if cov < 0.6: continue
                a = sum(_data(ref_l.crop(box))) / ((box[2]-box[0])*(box[3]-box[1]))
                c = sum(_data(ren_l.crop(box))) / ((box[2]-box[0])*(box[3]-box[1]))
                diffs += abs(a - c) / 255.0; cells += 1
        out.append({"band": i, "y_range_px": [by0, by1], "cells": cells,
                    "mean_luma_diff": round(diffs / cells, 3) if cells else None})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True); ap.add_argument("--render", required=True)
    ap.add_argument("--out", default="comparison.png"); ap.add_argument("--tol", type=int, default=40)
    ap.add_argument("--bands", type=int, default=8); ap.add_argument("--grid", type=int, default=48)
    ap.add_argument("--json", action="store_true", help="print one line: SILHOUETTE_COMPARE <json>")
    a = ap.parse_args()
    ref = Image.open(a.reference).convert("RGB"); ren = Image.open(a.render).convert("RGB")
    rm = fg_mask(ref, a.tol); nm = fg_mask(ren, a.tol)
    rbox = bbox(rm)
    if not rbox or not bbox(nm):
        err = {"error": "foreground not found in one image — check background/tolerance"}
        if a.json:
            print("SILHOUETTE_COMPARE " + json.dumps(err)); sys.exit(1)
        sys.exit(json.dumps(err))
    ren_al, nm_al = align(ren, nm, rbox, ref.size)
    score, inter_px = iou(rm, nm_al)
    shared = ImageChops.multiply(rm, nm_al)
    rb_w, rb_h = rbox[2]-rbox[0], rbox[3]-rbox[1]
    nb = bbox(nm); nb_w, nb_h = nb[2]-nb[0], nb[3]-nb[1]
    result = {
        "iou_after_alignment": round(score, 4),
        "aspect_ref_h_over_w": round(rb_h / rb_w, 3), "aspect_render_h_over_w": round(nb_h / nb_w, 3),
        "aspect_ratio_delta_pct": round(100 * (nb_h/nb_w - rb_h/rb_w) / (rb_h/rb_w), 1),
        "symmetry_parity_ref": symmetry_parity(rm), "symmetry_parity_render": symmetry_parity(nm),
        "interior_diff_bands": interior_bands(ref, ren_al, shared, a.bands, a.grid),
        "outline_cells_share_note": "IoU reads outline only; use bands + eyes for interior features",
        "advisory": "photo-vs-render: lighting/background differences inflate diffs; never optimise toward these numbers",
    }
    # sheet
    w, h = ref.size
    sheet = Image.new("RGB", (w*3, h), (30, 30, 30))
    sheet.paste(ref, (0, 0)); sheet.paste(ren_al, (w, 0))
    ov = Image.new("RGB", (w, h), (30, 30, 30)); ovp = ov.load(); rp = rm.load(); npx = nm_al.load()
    for y in range(h):
        for x in range(w):
            r, n = rp[x, y] > 0, npx[x, y] > 0
            if r and n: ovp[x, y] = (60, 200, 90)
            elif r: ovp[x, y] = (220, 60, 60)
            elif n: ovp[x, y] = (60, 110, 230)
    sheet.paste(ov, (2*w, 0))
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate(["reference", "render (aligned)", f"overlay IoU {score:.3f}"]):
        d.text((i*w + 6, 6), t, fill=(255, 255, 255))
    sheet.save(a.out); result["sheet"] = a.out
    if a.json:
        print("SILHOUETTE_COMPARE " + json.dumps(result))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
