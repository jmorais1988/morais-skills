"""Node-based PBR material from a texture folder (generic / Poly Haven / ambientCG / Substance Painter names) or an explicit map dict.

Live session (Blender:execute_blender_code): exec this file, then
    maps = find_maps(r"D:/tex/rock_2k")          # {'basecolor': path, 'normal': path, 'normal_convention': 'GL', ...}
    result = build_pbr_material("MAT_Rock", maps, projection='BOX', displacement='BUMP', macro_variation=0.3, obj="Rock")
or set PBR_OPTS before exec (same keys as the CLI, underscores):
    PBR_OPTS = {"folder": r"D:/tex/rock_2k", "name": "MAT_Rock", "object": "Rock", "projection": "BOX"}
Headless / CLI (prints one line: BUILD_PBR_MATERIAL <json report>):
    blender -b file.blend --python build_pbr_material.py -- --folder <dir> --name MAT_X [--object OBJ] [--prefix rock]
        [--map channel=path ...] [--projection UV|BOX|OBJECT] [--scale 1] [--box-blend 0.25] [--normal-strength 1]
        [--normal-convention GL|DX] [--displacement BUMP|DISPLACE|NONE] [--disp-scale 0.02] [--ao-to-basecolor 0]
        [--gltf-occlusion] [--macro-variation 0] [--roughness-range 0 1] [--save out.blend]

Map keys: basecolor, normal (+ normal_convention 'GL'|'DX', or key normal_dx), roughness, gloss (inverted), metallic,
height, ao, arm/orm (packed AO/Rough/Metal = R/G/B), opacity, emission. sRGB: basecolor/emission; Non-Color: the rest.
Filename tokens: Poly Haven _diff/_nor_gl/_nor_dx/_rough/_arm/_disp; ambientCG _Color/_NormalGL/_NormalDX/_Metalness/
_Displacement/_AmbientOcclusion; Substance Painter _BaseColor/_Normal/_OcclusionRoughnessMetallic/_Height/_Emissive/_Mixed_AO.
Substance Painter names don't encode the normal convention: pass normal_convention / --normal-convention (it overrides
the filename guess; UNKNOWN is assumed OpenGL with a warning).
Notes
- DirectX normals: Normal Map node `convention='DIRECTX'` (5.1+); older builds get a Separate/1-G/Combine green flip.
- Opacity maps set EEVEE `surface_render_method='DITHERED'` (4.2+; legacy blend_method is deprecated).
- An existing material with `name` is CLEARED and rebuilt.
- scale = texture repeats per UV unit (UV) or per metre (BOX/OBJECT; OBJECT = flat planar projection of object XY).
- BOX/OBJECT + tangent normal map is approximate (tangents still come from the UV map) - prefer UV for hero assets.
- DISPLACE wires Displacement -> Material Output and sets displacement method BOTH; needs dense/adaptive geometry.
- ao_to_basecolor multiplies AO into base colour: a FAKE for EEVEE / game previews (Cycles already occludes). Default 0.
- gltf_occlusion: group node "glTF Material Output" with float input "Occlusion" (what the bundled glTF exporter
  searches for: group name starting with "glTF Material Output" or legacy "glTF Settings") -> exported occlusionTexture.
- UDIM: tile-numbered sets (`Asset_BaseColor.1001.png`, `Asset_BaseColor_1001.png`, or an explicit
  `--map basecolor=dir/Asset_BaseColor.<UDIM>.png`) become ONE tiled image per channel (source 'TILED', filepath with
  `<UDIM>`). Tile rule: 1001-2000 after '.' always; after '_' only for 1001 or when >= 2 sibling tiles exist (so
  `rock_1024.png` stays a plain file). Loading a `<UDIM>` path with images.load() gives an empty FILE image in 5.2,
  so the lowest tile file is loaded and switched to TILED (Blender then scans the siblings). Report `udim` lists tiles
  per channel; a tile present in one map but missing in another is a warning (it renders the missing-tile colour).
  UDIM needs projection='UV'. `<UVTILE>` (u1_v1) names are not detected.
Returns `result` dict (JSON-serialisable).
"""
import bpy, os, re, sys, json, warnings

IMG_EXT = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.tga', '.exr', '.bmp', '.webp')
CHANNEL_TOKENS = {
    'basecolor': ('basecolor', 'albedo', 'diffuse', 'diff', 'col', 'color', 'colour', 'bc'),
    'normal': ('normal', 'nor', 'nrm', 'norm', 'normalgl', 'normaldx', 'nrml'),
    'roughness': ('roughness', 'rough', 'rgh'),
    'gloss': ('gloss', 'glossiness'),
    'metallic': ('metallic', 'metalness', 'metal', 'mtl'),
    'height': ('height', 'disp', 'displacement', 'heightmap'),
    'ao': ('ao', 'occlusion', 'ambientocclusion'),
    'arm': ('arm', 'orm', 'occlusionroughnessmetallic'),
    'opacity': ('opacity', 'alpha', 'transparency'),
    'emission': ('emission', 'emissive', 'emit'),
}
TOKEN2CH = {t: ch for ch, ts in CHANNEL_TOKENS.items() for t in ts}
SKIP_TOKEN = re.compile(r'^(\d+k|\d+|png|jpe?g|exr|tiff?|tga|gl|dx|opengl|directx|\d+bit)$')
NONCOLOR = {'normal', 'roughness', 'gloss', 'metallic', 'height', 'ao', 'arm', 'opacity'}
TILE_RE = re.compile(r'^(?P<base>.+?)(?P<sep>[._])(?P<tile>1\d{3}|2000)$')


def udim_tiles(path):
    """UDIM template + tiles on disk for `path` (a '<UDIM>' template or one tile file). Returns (template, [tiles]);
    (None, []) when the path is not a UDIM set. Tile rule: see module docstring."""
    d, fn = os.path.split(path)
    stem, ext = os.path.splitext(fn)
    if '<UDIM>' in fn.upper():
        i = fn.upper().index('<UDIM>'); pre, post = fn[:i], fn[i + 6:]
    else:
        m = TILE_RE.match(stem)
        if not m or not 1001 <= int(m['tile']) <= 2000:
            return None, []
        pre, post = m['base'] + m['sep'], ext
    rx = re.compile(re.escape(pre) + r'(\d{4})' + re.escape(post) + '$', re.I)
    try:
        tiles = sorted({int(mm.group(1)) for f in os.listdir(d or '.') for mm in [rx.match(f)]
                        if mm and 1001 <= int(mm.group(1)) <= 2000})
    except OSError:
        tiles = []
    if '<UDIM>' not in fn.upper() and not (pre.endswith('.') or int(m['tile']) == 1001 or len(tiles) >= 2):
        return None, []
    return os.path.join(d, pre + '<UDIM>' + post), tiles


def find_maps(folder, prefix=None):
    """Scan `folder` for PBR maps. Returns {channel: path, 'normal_convention': GL|DX|UNKNOWN, '_unmatched': [...],
    '_warnings': [...], '_udim': {channel: [tiles]}}. Channel = last meaningful filename token (resolution/format/GL/DX
    tokens skipped). UDIM tile files collapse to one '<UDIM>' template path per channel."""
    found, unmatched, bases, seen_tpl, udim = {}, [], {}, set(), {}
    for fn in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(fn)
        if ext.lower() not in IMG_EXT or (prefix and not fn.lower().startswith(prefix.lower())):
            continue
        tpl, tiles = udim_tiles(os.path.join(folder, fn))
        if tpl:
            if tpl.lower() in seen_tpl:
                continue
            seen_tpl.add(tpl.lower())
            fn = os.path.basename(tpl); stem = fn[:fn.upper().index('<UDIM>')].rstrip('._-')
        toks = [t for t in re.split(r'[_\-\s.]+', stem.lower()) if t]
        idx = next((i for i in range(len(toks) - 1, -1, -1) if not SKIP_TOKEN.match(toks[i])), None)
        ch = TOKEN2CH.get(toks[idx]) if idx is not None else None
        if ch is None:
            unmatched.append(fn); continue
        conv = None
        if ch == 'normal':
            conv = 'DX' if any(t in ('dx', 'directx', 'normaldx') for t in toks) else \
                   'GL' if any(t in ('gl', 'opengl', 'normalgl') for t in toks) else 'UNKNOWN'
        rank = ({'GL': 0, 'UNKNOWN': 1, 'DX': 2}[conv] if conv else 0, IMG_EXT.index(ext.lower()))
        bases.setdefault(ch, set()).add('_'.join(toks[:idx]))
        if ch not in found or rank < found[ch][0]:
            found[ch] = (rank, os.path.join(folder, fn), conv)
            if tpl: udim[ch] = tiles
            else: udim.pop(ch, None)
    out = {ch: v[1] for ch, v in found.items()}
    if 'normal' in found:
        out['normal_convention'] = found['normal'][2]
    out['_unmatched'] = unmatched
    out['_warnings'] = [f"several texture sets for '{ch}' {sorted(b)}: pass prefix=" for ch, b in bases.items() if len(b) > 1]
    out['_udim'] = udim
    return out


def _sock(coll, names, what):
    for key in ('identifier', 'name'):
        for n in names:
            for s in coll:
                if getattr(s, key) == n and getattr(s, 'enabled', True):
                    return s
    raise KeyError(f"{what}: none of {names} in {[s.identifier for s in coll]}")


def IN(node, *names): return _sock(node.inputs, names, node.bl_idname + ' input')
def OUT(node, *names): return _sock(node.outputs, names, node.bl_idname + ' output')


def _material(name):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    with warnings.catch_warnings():  # Material.use_nodes is deprecated in 5.x (always node-based)
        warnings.simplefilter('ignore')
        if mat.node_tree is None or not getattr(mat, 'use_nodes', True):
            mat.use_nodes = True
    mat.node_tree.nodes.clear()
    return mat


def set_displacement_method(mat, value='BOTH'):
    """4.1+: material.displacement_method; older: material.cycles.displacement_method. Returns the path used."""
    for owner, path in ((mat, 'material.displacement_method'), (getattr(mat, 'cycles', None), 'material.cycles.displacement_method')):
        if owner is not None and hasattr(owner, 'displacement_method'):
            owner.displacement_method = value
            return path
    return None


def gltf_output_group():
    grp = bpy.data.node_groups.get('glTF Material Output')
    if grp is None:
        grp = bpy.data.node_groups.new('glTF Material Output', 'ShaderNodeTree')
        grp.nodes.new('NodeGroupOutput'); grp.nodes.new('NodeGroupInput').location = (-200, 0)
    if not any(getattr(i, 'item_type', 'SOCKET') == 'SOCKET' and i.in_out == 'INPUT' and i.name == 'Occlusion'
               for i in grp.interface.items_tree):
        grp.interface.new_socket('Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
    return grp


X = dict(coord=-2100, map=-1900, img=-1600, p1=-1250, p2=-1050, p3=-850, bsdf=-400, out=100)
Y = dict(macro=950, basecolor=650, arm=300, metallic=300, roughness=0, gloss=0, normal=-350, height=-700, ao=-1000,
         opacity=-1250, emission=-1450, mapping=0)


def build_pbr_material(name, maps, *, projection='UV', scale=1.0, box_blend=0.25, normal_strength=1.0, displacement='BUMP',
                       disp_scale=0.02, ao_to_basecolor=0.0, gltf_occlusion=False, macro_variation=0.0,
                       roughness_range=(0.0, 1.0), obj=None, normal_convention=None):
    projection, displacement = projection.upper(), displacement.upper()
    assert projection in ('UV', 'BOX', 'OBJECT') and displacement in ('BUMP', 'DISPLACE', 'NONE')
    maps = {k.lower(): v for k, v in (maps or {}).items() if not k.startswith('_')}
    if maps.get('orm') and not maps.get('arm'): maps['arm'] = maps.pop('orm')
    conv = str(maps.get('normal_convention') or 'UNKNOWN').upper()
    if maps.get('normal_dx') and not maps.get('normal'): maps['normal'], conv = maps['normal_dx'], 'DX'
    rep = {"material": name, "projection": projection, "displacement": displacement, "maps_used": {}, "colorspaces": {},
           "missing": [], "warnings": [], "notes": []}
    if normal_convention:
        forced = {'GL': 'GL', 'OPENGL': 'GL', 'DX': 'DX', 'DIRECTX': 'DX'}[str(normal_convention).upper()]
        if conv in ('GL', 'DX') and conv != forced:
            rep["warnings"].append(f"normal_convention={forced} overrides filename convention {conv}")
        conv = forced
    udim = {}
    for ch in list(CHANNEL_TOKENS):
        if not maps.get(ch):
            continue
        tpl, tiles = udim_tiles(maps[ch])
        if tpl:
            maps[ch] = tpl
            if tiles: udim[ch] = tiles
        if (tpl and not tiles) or (not tpl and not os.path.isfile(maps[ch])):
            rep["warnings"].append(f"{ch}: file not found {maps[ch]}"); maps.pop(ch)
    if udim:
        every = sorted(set().union(*udim.values()))
        rep["udim"] = {"tiles": every, "per_channel": udim}
        for ch, tiles in udim.items():
            miss = [t for t in every if t not in tiles]
            if miss:
                rep["warnings"].append(f"{ch}: UDIM tile(s) {miss} missing (present in "
                                       f"{sorted(c for c, t in udim.items() if set(miss) & set(t))}) - renders the missing-tile colour")
        flat = sorted(ch for ch in CHANNEL_TOKENS if maps.get(ch) and ch not in udim)
        if flat:
            rep["warnings"].append(f"non-UDIM map(s) {flat} in a UDIM set: one image repeats on every tile")
        if projection != 'UV':
            rep["warnings"].append(f"UDIM tiles need projection='UV' (got {projection})")

    mat = _material(name); nt = mat.node_tree; N, L = nt.nodes, nt.links
    frames = {}

    def frame(key, label):
        if key not in frames:
            f = N.new('NodeFrame'); f.name, f.label = f"FRAME_{key}", label; frames[key] = f
        return frames[key]

    def node(t, nm, label, x, y, fr=None, **props):
        n = N.new(t); n.name, n.label = nm, label
        for k, v in props.items(): setattr(n, k, v)
        if fr is not None: n.parent = fr
        n.location = (X[x] if isinstance(x, str) else x, Y[y] if isinstance(y, str) else y)
        return n

    link = L.new
    out = node('ShaderNodeOutputMaterial', 'Material Output', 'Material Output', 'out', 0)
    bsdf = node('ShaderNodeBsdfPrincipled', 'Principled BSDF', 'Principled BSDF', 'bsdf', 0)
    link(OUT(bsdf, 'BSDF'), IN(out, 'Surface'))
    fm = frame('mapping', f"Mapping ({projection}, scale {scale})")
    coord = node('ShaderNodeTexCoord', 'TexCoord', 'Texture Coordinate', 'coord', 'mapping', fm)
    mapn = node('ShaderNodeMapping', 'Mapping', f'Mapping x{scale}', 'map', 'mapping', fm)
    IN(mapn, 'Scale').default_value = (scale, scale, scale)
    link(OUT(coord, 'UV' if projection == 'UV' else 'Object'), IN(mapn, 'Vector'))

    def load_tiled(tpl, tiles):
        want = os.path.normcase(os.path.abspath(tpl))
        img = next((i for i in bpy.data.images if i.source == 'TILED'
                    and os.path.normcase(os.path.abspath(bpy.path.abspath(i.filepath))) == want), None)
        if img is None:  # images.load('<UDIM>' path) -> empty FILE image in 5.2; load a real tile, then switch
            first = tpl[:tpl.upper().index('<UDIM>')] + str(tiles[0]) + tpl[tpl.upper().index('<UDIM>') + 6:]
            img = bpy.data.images.load(first, check_existing=False)
            img.source = 'TILED'  # Blender scans sibling tiles and rewrites filepath to <UDIM>
        have = {t.number for t in img.tiles}
        if not set(tiles) <= have or '<UDIM>' not in img.filepath.upper():
            for t in tiles:
                if t not in have: img.tiles.new(tile_number=t)
            img.filepath = tpl; img.reload()
        return img

    def tex(ch, path, label):
        if ch in udim:
            img = load_tiled(path, udim[ch])
            rep["udim"].setdefault("images", {})[ch] = {"image": img.name, "source": img.source,
                                                        "tiles": [t.number for t in img.tiles]}
        else:
            img = bpy.data.images.load(path, check_existing=True)
        img.colorspace_settings.name = 'Non-Color' if ch in NONCOLOR else 'sRGB'
        n = node('ShaderNodeTexImage', f"TEX_{ch}", f"{label}: {os.path.basename(path)}", 'img', ch, frame(ch, label),
                 image=img, projection='BOX' if projection == 'BOX' else 'FLAT', projection_blend=box_blend)
        link(OUT(mapn, 'Vector'), IN(n, 'Vector'))
        rep["maps_used"][ch] = path; rep["colorspaces"][ch] = img.colorspace_settings.name
        return n

    def mix(kind, blend, fac, nm, label, x, y, fr):
        n = node('ShaderNodeMix', nm, label, x, y, fr, data_type=kind)
        if kind == 'RGBA': n.blend_type = blend
        IN(n, 'Factor_Float', 'Factor').default_value = fac
        sfx = 'Color' if kind == 'RGBA' else 'Float'
        return n, IN(n, f'A_{sfx}'), IN(n, f'B_{sfx}'), OUT(n, f'Result_{sfx}')

    # --- packed ARM / AO ---
    sep_arm, ao = None, None
    if maps.get('arm'):
        t = tex('arm', maps['arm'], 'ARM packed (R=AO G=Rough B=Metal)')
        sep_arm = node('ShaderNodeSeparateColor', 'ARM_Split', 'Split ARM', 'p1', 'arm', frames['arm'])
        link(OUT(t, 'Color'), IN(sep_arm, 'Color'))
    if maps.get('ao'):
        ao = OUT(tex('ao', maps['ao'], 'Ambient Occlusion'), 'Color')
    elif sep_arm:
        ao = OUT(sep_arm, 'Red'); rep["maps_used"]['ao'] = 'arm.R'
    # --- macro variation noise ---
    noise = None
    if macro_variation > 0:
        fr = frame('macro', f'Macro variation {macro_variation} (anti-tiling)')
        nz = node('ShaderNodeTexNoise', 'MacroNoise', 'Low-freq noise (object space)', 'img', 'macro', fr)
        IN(nz, 'Scale').default_value, IN(nz, 'Detail').default_value = 0.6, 2.0
        link(OUT(coord, 'Object'), IN(nz, 'Vector'))
        noise = OUT(nz, 'Fac', 'Factor')
    # --- base colour ---
    base = None
    if maps.get('basecolor'):
        base = OUT(tex('basecolor', maps['basecolor'], 'Base Color'), 'Color')
    else:
        rep["missing"].append('basecolor'); rep["warnings"].append("no basecolor map: constant grey 0.8")
    fb = frame('basecolor', 'Base Color')
    if ao_to_basecolor > 0:
        if ao is None:
            rep["warnings"].append("ao_to_basecolor > 0 but no AO/ARM map")
        else:
            _, a, b, r = mix('RGBA', 'MULTIPLY', ao_to_basecolor, 'AO_Multiply', 'AO x base (FAKE, preview only)', 'p2', 'basecolor', fb)
            a.default_value = (0.8, 0.8, 0.8, 1)
            if base: link(base, a)
            link(ao, b); base = r
            rep["notes"].append("AO multiplied into base colour: fake occlusion for EEVEE/game preview; do not bake/export it")
    if noise is not None:
        _, a, b, r = mix('RGBA', 'OVERLAY', macro_variation, 'Macro_BaseColor', 'Overlay macro noise', 'p3', 'basecolor', fb)
        a.default_value = (0.8, 0.8, 0.8, 1)
        if base: link(base, a)
        link(noise, b); base = r
    if base: link(base, IN(bsdf, 'Base Color'))
    # --- roughness ---
    rough = None
    if maps.get('roughness'):
        rough = OUT(tex('roughness', maps['roughness'], 'Roughness'), 'Color')
    elif maps.get('gloss'):
        t = tex('gloss', maps['gloss'], 'Gloss (inverted to roughness)')
        inv = node('ShaderNodeMath', 'Gloss_Invert', '1 - gloss', 'p1', 'gloss', frames['gloss'], operation='SUBTRACT')
        IN(inv, 'Value').default_value = 1.0
        link(OUT(t, 'Color'), IN(inv, 'Value_001')); rough = OUT(inv, 'Value')
        rep["notes"].append("gloss map inverted to roughness")
    elif sep_arm:
        rough = OUT(sep_arm, 'Green'); rep["maps_used"]['roughness'] = 'arm.G'
    fr_r = frame('roughness', f'Roughness -> range {tuple(roughness_range)}')
    if rough is None:
        rep["missing"].append('roughness')
        rep["warnings"].append("no roughness map: constant 0.5 - roughness must vary; add macro_variation or a derived map"
                               + (" (macro_variation drives it now)" if noise is not None else ""))
    if noise is not None:
        _, a, b, r = mix('FLOAT', None, min(1.0, 0.35 * macro_variation), 'Macro_Roughness', 'Macro noise into roughness', 'p2', 'roughness', fr_r)
        a.default_value = 0.5
        if rough: link(rough, a)
        link(noise, b); rough = r
    if rough is not None:
        mr = node('ShaderNodeMapRange', 'Roughness_Range', 'Roughness range', 'p3', 'roughness', fr_r, clamp=True)
        IN(mr, 'To Min').default_value, IN(mr, 'To Max').default_value = roughness_range
        link(rough, IN(mr, 'Value')); link(OUT(mr, 'Result'), IN(bsdf, 'Roughness'))
    else:
        IN(bsdf, 'Roughness').default_value = 0.5
    # --- metallic ---
    if maps.get('metallic'):
        link(OUT(tex('metallic', maps['metallic'], 'Metallic'), 'Color'), IN(bsdf, 'Metallic'))
    elif sep_arm:
        link(OUT(sep_arm, 'Blue'), IN(bsdf, 'Metallic')); rep["maps_used"]['metallic'] = 'arm.B'
    else:
        rep["missing"].append('metallic'); rep["notes"].append("no metallic map: constant 0 (right for dielectrics)")
    # --- normal ---
    nrm = None
    if maps.get('normal'):
        t = tex('normal', maps['normal'], f'Normal ({conv})'); col = OUT(t, 'Color'); fn = frames['normal']
        nm = node('ShaderNodeNormalMap', 'NormalMap', 'Normal Map (tangent)', X['bsdf'] - 300, 'normal', None, space='TANGENT')
        if conv == 'DX' and 'convention' in nm.bl_rna.properties:  # 5.1+: built-in Y flip
            nm.convention = 'DIRECTX'; nm.label = 'Normal Map (tangent, DirectX)'
            rep["notes"].append("DirectX normal: Normal Map node convention DIRECTX")
        elif conv == 'DX':  # before 5.1: flip green manually
            sep = node('ShaderNodeSeparateColor', 'DX_Split', 'Split DX normal', 'p1', 'normal', fn)
            flip = node('ShaderNodeMath', 'DX_FlipGreen', 'Flip green (1-G)', 'p2', Y['normal'] - 60, fn, operation='SUBTRACT')
            comb = node('ShaderNodeCombineColor', 'DX_Combine', 'DX -> GL', 'p3', 'normal', fn)
            IN(flip, 'Value').default_value = 1.0
            link(col, IN(sep, 'Color')); link(OUT(sep, 'Red'), IN(comb, 'Red')); link(OUT(sep, 'Blue'), IN(comb, 'Blue'))
            link(OUT(sep, 'Green'), IN(flip, 'Value_001')); link(OUT(flip, 'Value'), IN(comb, 'Green'))
            col = OUT(comb, 'Color'); rep["notes"].append("DirectX normal: green flipped to OpenGL (no Normal Map convention option)")
        elif conv == 'UNKNOWN':
            rep["warnings"].append("normal convention not in filename: assumed OpenGL - pass normal_convention='DX' "
                                   "(--normal-convention DX) for DirectX exports such as Substance Painter DX presets")
        rep["normal_convention"] = conv
        IN(nm, 'Strength').default_value = normal_strength
        link(col, IN(nm, 'Color')); nrm = OUT(nm, 'Normal')
        if projection != 'UV':
            rep["warnings"].append(f"{projection} projection + tangent normal map: approximate shading (tangents from UV)")
    else:
        rep["missing"].append('normal')
    # --- height ---
    if maps.get('height') and displacement != 'NONE':
        t = tex('height', maps['height'], f'Height ({displacement})'); fh = frames['height']
        if displacement == 'BUMP':
            bump = node('ShaderNodeBump', 'HeightBump', f'Bump (distance {disp_scale})', X['bsdf'] - 300, 'height', None)
            IN(bump, 'Distance').default_value = disp_scale
            link(OUT(t, 'Color'), IN(bump, 'Height'))
            if nrm: link(nrm, IN(bump, 'Normal'))
            nrm = OUT(bump, 'Normal')
        else:
            d = node('ShaderNodeDisplacement', 'HeightDisplacement', f'Displacement (scale {disp_scale})', 'p3', 'height', fh)
            IN(d, 'Scale').default_value, IN(d, 'Midlevel').default_value = disp_scale, 0.5
            link(OUT(t, 'Color'), IN(d, 'Height')); link(OUT(d, 'Displacement'), IN(out, 'Displacement'))
            rep["displacement_method_prop"] = set_displacement_method(mat, 'BOTH')
            rep["notes"].append("true displacement: needs dense mesh or adaptive subdivision; midlevel 0.5")
    elif maps.get('height'):
        rep["notes"].append("height map ignored (displacement='NONE')")
    else:
        rep["missing"].append('height')
    if nrm: link(nrm, IN(bsdf, 'Normal'))
    # --- opacity / emission ---
    if maps.get('opacity'):
        link(OUT(tex('opacity', maps['opacity'], 'Opacity'), 'Color'), IN(bsdf, 'Alpha'))
        mat.surface_render_method = 'DITHERED'  # EEVEE 4.2+ (blend_method is deprecated)
        rep["surface_render_method"] = mat.surface_render_method
    if maps.get('emission'):
        link(OUT(tex('emission', maps['emission'], 'Emission'), 'Color'), IN(bsdf, 'Emission Color', 'Emission'))
        IN(bsdf, 'Emission Strength').default_value = 1.0
    # --- glTF occlusion ---
    if gltf_occlusion:
        if ao is None:
            rep["warnings"].append("gltf_occlusion requested but no AO/ARM map")
        else:
            g = node('ShaderNodeGroup', 'glTF Material Output', 'glTF Material Output', 'out', 'ao', None)
            g.node_tree = gltf_output_group(); link(ao, IN(g, 'Occlusion'))
            rep["gltf_occlusion"] = "group 'glTF Material Output' input 'Occlusion'"
    if not rep["maps_used"]:
        rep["warnings"].append("no maps found at all - check folder/prefix")
    # --- assign ---
    if obj is not None:
        o = bpy.data.objects.get(obj) if isinstance(obj, str) else obj
        if o is None or not hasattr(o.data, 'materials'):
            rep["warnings"].append(f"object {obj!r} not found or has no material slots")
        else:
            if len(o.data.materials): o.data.materials[0] = mat
            else: o.data.materials.append(mat)
            rep["assigned_to"] = o.name
            if projection == 'UV' and o.type == 'MESH' and not o.data.uv_layers:
                rep["warnings"].append(f"{o.name} has no UV map but projection='UV'")
    rep["nodes"] = {n.name: n.bl_idname for n in N if n.bl_idname != 'NodeFrame'}
    rep["summary"] = (f"{name}: {len(rep['maps_used'])} channels {sorted(rep['maps_used'])}, missing {rep['missing']}, "
                      f"{len(rep['warnings'])} warning(s)")
    return rep


def _run(o):
    maps = find_maps(o["folder"], o.get("prefix")) if o.get("folder") else {}
    maps.update(o.get("maps") or {})
    kw = {k: o[k] for k in ("projection", "scale", "box_blend", "normal_strength", "displacement", "disp_scale",
                            "ao_to_basecolor", "gltf_occlusion", "macro_variation", "roughness_range", "normal_convention")
          if o.get(k) is not None}
    rep = build_pbr_material(o["name"], maps, obj=o.get("object"), **kw)
    rep["find_maps"] = {k: v for k, v in maps.items() if k.startswith('_') and v}
    if o.get("save"):
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(o["save"])); rep["saved"] = os.path.abspath(o["save"])
    return rep


def _cli(argv):
    import argparse
    p = argparse.ArgumentParser(prog="build_pbr_material.py")
    p.add_argument("--folder"); p.add_argument("--prefix"); p.add_argument("--name", required=True); p.add_argument("--object")
    p.add_argument("--map", action="append", default=[], help="channel=path")
    p.add_argument("--projection"); p.add_argument("--displacement")
    p.add_argument("--normal-convention", type=str.upper, choices=("GL", "DX", "OPENGL", "DIRECTX"))
    for f in ("scale", "box-blend", "normal-strength", "disp-scale", "ao-to-basecolor", "macro-variation"):
        p.add_argument("--" + f, type=float)
    p.add_argument("--roughness-range", type=float, nargs=2); p.add_argument("--gltf-occlusion", action="store_true", default=None)
    p.add_argument("--save")
    a = vars(p.parse_args(argv))
    a["maps"] = dict(kv.split("=", 1) for kv in a.pop("map"))
    return _run(a)


_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if globals().get("PBR_OPTS"):
    result = _run(dict(PBR_OPTS))
elif "--name" in _argv:
    result = _cli(_argv)
else:
    result = {"ready": "call find_maps(folder) / build_pbr_material(name, maps, ...)"}
if "summary" in result:
    print("BUILD_PBR_MATERIAL " + json.dumps(result))
