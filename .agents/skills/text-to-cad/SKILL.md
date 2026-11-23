---
name: text-to-cad
description: Route manufacturable parts and mechanisms to the text-to-cad plugin (earthtojake/text-to-cad) — parametric build123d CAD with STEP/STL/3MF/DXF export, joints and kinematics, CNC/sheet-metal/molding/3D-print checks, engineering drawings, FEA and URDF. Use when the person needs real dimensions and tolerances, a part to print, machine, cut or order, or a CAD file (STEP, DXF) rather than a Blender mesh; also to install text-to-cad when its `cad` skill isn't available.
---

# text-to-cad

[earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad) (MIT) is a plugin, not a text skill. Its `cad` skill runs everything through the `cad` command (a server plus a live viewer), so it's **not vendored here**. This file decides when to use it and how to get it.

## CAD or Blender?

- **text-to-cad:** exact dimensions and fits, parts that are printed, machined, laser-cut, bent or molded, STEP/DXF deliverables, joints with real kinematics, stress checks, drawings, robot URDF/MJCF.
- **Blender** (`anymachine`, `hard-surface-toolkit`, `hard-surface-props`, `blender-3d-modeling`): game and film assets, art-directed looks, rigs for engines, renders.
- **Both:** design the part in CAD, export GLB/STL, then bring it into Blender for lookdev and rendering. text-to-cad's own `render` skill also renders in Blender.

## If the `cad` skill is available

Use it and follow its `SKILL.md`. This file adds nothing beyond the routing above.

## If it isn't installed

Don't run the installer yourself. Give the person these commands to run:

```bash
uv tool install cad                                     # needs uv; Python 3.11+
claude plugin marketplace add earthtojake/text-to-cad#latest
claude plugin install text-to-cad@earthtojake          # then restart Claude Code
```

Other agent apps are listed in upstream [docs/install.md](https://github.com/earthtojake/text-to-cad/blob/main/docs/install.md). Their one-line installer (`irm https://www.texttocad.dev/install.ps1 | iex` on Windows) also installs the plugin in every agent app it finds and **turns on automatic updates**. Install it once per app, because two copies show every skill twice.

cad sends usage stats and crash reports by default. `cad telemetry off`, or `DO_NOT_TRACK=1` set wherever it runs, turns them off.
