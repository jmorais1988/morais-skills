import bpy, math, os, mathutils
import tempfile
# Output folder: set the AUDIT_SHOTS_DIR env var or assign viewport_shots.SHOTS before calling shot().
SHOTS = os.environ.get("AUDIT_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "audit_shots")
VIEWS = {  # name: (direction from target to camera, up)
 'FRONT': ((1,0,0),(0,0,1)), 'BACK': ((-1,0,0),(0,0,1)), 'LEFT': ((0,1,0),(0,0,1)), 'RIGHT': ((0,-1,0),(0,0,1)),
 'TOP': ((0,0,1),(1,0,0)), 'BOTTOM': ((0,0,-1),(1,0,0)),
 'ISO_FL': ((1,-0.9,0.55),(0,0,1)), 'ISO_RL': ((-1,-0.9,0.55),(0,0,1)), 'ISO_FR': ((1,0.9,0.55),(0,0,1)), 'ISO_RR': ((-1,0.9,0.55),(0,0,1)),
}
def _area():
    for w in bpy.context.window_manager.windows:
        for a in w.screen.areas:
            if a.type=='VIEW_3D':
                return w,a,[r for r in a.regions if r.type=='WINDOW'][0]
def shot(name, view='FRONT', mode='SOLID', ortho=True, scale=5.2, res=(1600,900), target=(0,0,0.8), dist=12, hide=(), only=None, lens=40, overlays=False, wire=False, xray=False):
    sc=bpy.context.scene
    cam=bpy.data.objects.get('ShotCam')
    if cam is None:
        cd=bpy.data.cameras.new('ShotCam'); cam=bpy.data.objects.new('ShotCam',cd); sc.collection.objects.link(cam)
    d=mathutils.Vector(VIEWS[view][0]).normalized(); t=mathutils.Vector(target)
    cam.location=t+d*dist
    up=mathutils.Vector(VIEWS[view][1])
    q=(-d).to_track_quat('-Z','Y')
    if view=='TOP': q=mathutils.Euler((0,0,0)).to_quaternion()
    if view=='BOTTOM': q=mathutils.Euler((math.pi,0,0)).to_quaternion()
    cam.rotation_euler=q.to_euler()
    cam.data.type='ORTHO' if ortho else 'PERSP'; cam.data.ortho_scale=scale; cam.data.lens=lens; cam.data.clip_end=200
    old_cam=sc.camera; sc.camera=cam
    rx,ry=sc.render.resolution_x,sc.render.resolution_y; sc.render.resolution_x,sc.render.resolution_y=res; sc.render.resolution_percentage=100
    # visibility
    saved={}
    objs=[o for o in bpy.data.objects if o.type in('MESH','CURVE')]
    for o in objs:
        saved[o.name]=o.hide_viewport
        if only is not None: o.hide_viewport = not any(o.name==n or o.name.startswith(n) for n in only)
        elif hide: o.hide_viewport = o.hide_viewport or any(o.name==n or o.name.startswith(n) for n in hide)
    w,a,r=_area(); sp=a.spaces.active
    old=(sp.shading.type, sp.overlay.show_overlays, sp.region_3d.view_perspective, sp.shading.show_xray, sp.shading.color_type)
    sp.shading.type=mode; sp.overlay.show_overlays=overlays; sp.shading.show_xray=xray
    if mode=='SOLID': sp.shading.color_type='MATERIAL'; sp.shading.light='STUDIO'
    sp.region_3d.view_perspective='CAMERA'
    with bpy.context.temp_override(window=w, area=a, region=r):
        bpy.ops.view3d.view_camera() if sp.region_3d.view_perspective!='CAMERA' else None
        bpy.ops.render.opengl(view_context=True)
    os.makedirs(SHOTS, exist_ok=True); p=os.path.join(SHOTS,name+'.png'); bpy.data.images['Render Result'].save_render(p)
    sp.shading.type,sp.overlay.show_overlays,sp.region_3d.view_perspective,sp.shading.show_xray,sp.shading.color_type=old
    for o in objs: o.hide_viewport=saved[o.name]
    sc.render.resolution_x,sc.render.resolution_y=rx,ry; sc.camera=old_cam
    return p
