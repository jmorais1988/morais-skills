# Jewelry & Casting

Read this for rings, stone settings and any pattern that goes to a casting house: ring size tables, castable-resin minimums, casting geometry and shrinkage, stone proportions and seats, the `scripts/ring_builder.py` generator with its measured gates, and sprue guidance. Units, merge thresholds, per-process minimums, mesh checks and export verification are governed by `3d-printing.md` (§2, §3, §5–6); this file only adds the casting-specific numbers. `scripts/project_state.py` ships a `jewelry` profile (target → references → size → band → stone → seat → head → ring-gates → shrink → print-gate → export-verified).

## Contents
1. Ring sizes
2. Castable minimums
3. Casting geometry and shrinkage
4. Stones and seats
5. Ring generator and gates (`scripts/ring_builder.py`)
6. Sprues
7. Common failures

## 1. Ring sizes

Inner diameter; ISO 8653 size = inner circumference in mm; US ≈ 11.63 + 0.8128 × size mm:

| US | UK | EU/ISO | ID mm | | US | UK | EU/ISO | ID mm |
|---|---|---|---|---|---|---|---|---|
| 4 | H | 46 | 14.8 | | 9 | R | 59 | 19.0 |
| 5 | J | 49 | 15.7 | | 10 | T | 62 | 19.8 |
| 6 | L | 51 | 16.5 | | 11 | V | 64 | 20.6 |
| 7 | N | 54 | 17.3 | | 12 | X | 66 | 21.4 |
| 8 | P | 57 | 18.1 | | 13 | Z | 69 | 22.2 |

Wide bands (> 6 mm) fit tighter — go ~½ size up `[unverified]`. Model the bore exactly at size, then add casting shrinkage (§3).

## 2. Castable minimums

Formlabs castable-resin white paper unless marked:

| Feature | Minimum |
|---|---|
| Walls in structural stone settings | 0.5 mm (0.75 mm prints and files cleanly; 0.3 mm distorts) |
| Prongs | ≥ 0.5 mm (0.7 mm used on 2.5 mm side stones; center stones proportionally larger, typically 0.8–1.2 mm `[unverified]`) |
| Bezel | 0.4 mm on 2.5 mm stones (0.3 prints but risks casting/finishing) |
| Hollow forms | 0.7–0.9 mm walls |
| Through holes | ≥ 0.5 mm (1.5 mm casts reliably) |
| Engraving | 0.3–0.5 mm deep; letters ≥ 1.5 mm tall still fail in ornate script |
| Wire detail | 0.3 mm is lost in polishing — exaggerate relief |
| Ring shank | ≥ 1.0–1.5 mm thick for daily wear `[unverified; metal-dependent]` |

General resin/FDM/SLS walls, detail and clearances: `3d-printing.md` §3.

## 3. Casting geometry and shrinkage

**Casting-specific geometry**: add ~5° draft to prongs and walls that sit close together (thin investment between them breaks and floods); fillet internal corners (sharp investment edges break off, turbulence → porosity); keep models watertight and **booleaned into one solid**, not grouped shells.

**Shrinkage**: total pattern-to-metal shrinkage depends on route. Rubber mold → wax → cast chains reach 6–12 % (Stuller); direct print-to-cast (castable resin/wax) is lower, metal solidification alone ~1–2.5 % (platinum ~1–1.5, gold ~1–2, silver ~1.5–2.5) `[unverified; sources disagree — use the caster's figure]`. Scale uniformly by 1/(1−s) — but stone seats must fit stones after shrink, so seats are the dimension to check.

## 4. Stones and seats

Keep gems as **separate objects** (never booleaned into the metal; they are for render and for cutting seats). Round brilliant (Tolkowsky): table 53 %, crown angle 34.5°, pavilion angle 40.75°, crown height 16.2 %, pavilion depth 43.1 %, total ≈ 59.3 % + girdle (≈ 1–3 %) of diameter. Seat: bearing ledge at girdle height with the girdle diameter + 0.05–0.1 mm clearance `[unverified]`; cut the seat with a stone-shaped cutter (pavilion cone + girdle cylinder) so the culet (43 % of diameter below the girdle) clears the metal; open the seat through (culet hole) for light and cleaning.

## 5. Ring generator and gates (`scripts/ring_builder.py`)

Headless or live: `--size US7 | EU54 | UK N | ID17.3`, band width/thickness, round-brilliant proxy (Tolkowsky), stone-offset seat cutter (`--seat-clearance`), N vertical prongs (`--prongs`) + gallery rail, band top flared under the head so prongs land on metal (`--tip-frac`), `--shrink` for the pattern scale. Objects `RING_Band`, `RING_Head`, `RING_Metal` (union, the casting solid), `GEM_Stone`, `CUT_Seat`. Metal is written as the pattern (× 1/(1−shrink)); gates evaluate after shrink:

| Gate | Clean: US 7, 6.5 mm stone, 4 × 1.0 mm prongs, 1.5 % shrink (measured) | Planted defect (measured) |
|---|---|---|
| bore vs size ± 0.05 | 17.320 vertex / 17.314 flat vs 17.320 | no shrink compensation at 3 %: 16.800 flagged |
| prong free-section width ≥ 0.8 | 1.000 | 0.5 mm prongs: 0.500 flagged |
| notch wall behind the seat ≥ 0.5 | 0.687 | 0.5 mm prongs: 0.335 flagged |
| seat Ø at girdle ≥ girdle Ø | 6.600 (0.050/side) | seat −0.1: 6.300; uncompensated 3 %: 6.402 flagged |
| stone inside metal ≤ 0.01 mm (normal sign + 3-ray parity) | 0 of 20 098 samples, min gap 0.048 | seat −0.1: 316 samples, 0.096 mm; uncompensated: 0.045 mm flagged |

`--print-gate` runs `export_print.py` (`3d-printing.md` §5) on `RING_Metal`; pass = manifold, 0 intersecting pairs, area share thinner than `--min-wall-mm` ≤ 0.5 % (the raw ray minimum always catches a few samples on junction/flare edges: clean 0.06 mm min but 0.10 % of area). Clean: 1 shell, 0 pairs, 0.10 %; 0.5 mm prongs at `--min-wall-mm 0.8`: 10.4 % flagged. Boolean n-gons are concave: fan-triangulating tools report fake intersections and thin walls on them — the generator ear-clip triangulates its output. EU 54 × 6 prongs (5 mm stone) also passes with `--tip-frac 1.0`.

Export and bbox re-import proof (US-7 ring 20.500 × 20.500 × 2.000 mm, bore 17.300 mm from the file): `3d-printing.md` §6.

## 6. Sprues

`[unverified; caster decides]`: attach to the thickest section, feed thin from thick, no sprue on detailed or visible faces, ring sprue diameter ~2.5–3.5 mm; many casters prefer to add sprues themselves — ask.

## 7. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Ring cast a half size small | shrinkage ignored, or wide band | scale per caster's shrinkage; wide bands size up (§1, §3) |
| Bore gate flags 16.800 on a US 7 | no shrink compensation at 3 % | write the metal as pattern × 1/(1−s); gates evaluate after shrink (§5) |
| Investment breaks, porosity near prongs | thin investment between vertical walls, sharp inner corners | 5° draft, fillets, wider gaps (§3) |
| Stone doesn't seat after casting | seat modeled at stone size, shrink not compensated | compensate, verify seat Ø after scale (seat Ø ≥ girdle Ø gate, §4–5) |
| Stone intersects the metal (samples inside) | seat cutter too small (seat −0.1) or uncompensated shrink | `--seat-clearance` 0.05–0.1; stone-inside-metal gate ≤ 0.01 mm (§5) |
| Prongs vanish or turn spiky after cleanup | Merge by Distance / Weld default 0.1 mm collapsed a 0.3 mm prong (48 → 14 verts) | threshold ≤ 1/10 of the smallest feature (`3d-printing.md` §2) |
| Prong flagged thin / distorts in print | 0.3–0.5 mm prongs below the 0.8 free-section gate; 0.3 mm walls distort | prongs ≥ 0.7–1.0 mm, walls ≥ 0.5 mm (§2, §5) |
| Fake intersections / thin walls reported on a clean ring | concave boolean n-gons fan-triangulated by the checker | ear-clip triangulate (the generator does) before `--print-gate` (§5) |
| Engraving unreadable after polish | detail < 0.3 mm deep or script letters < 1.5 mm | 0.3–0.5 mm deep, exaggerate relief (§2) |
| Slicer / caster reports grouped shells | band, head and prongs not unioned | boolean into one solid `RING_Metal`; gems stay separate objects (§3–4) |
