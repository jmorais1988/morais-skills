"""Template for a task-specific helper tool: one Operator (with redo-panel properties) + one N-panel.

Copy, rename `MH_OT_example` / `bl_idname`, implement `execute`, then register in the live session with
Blender:execute_blender_code (exec this file's text). Call via `bpy.ops.model_helpers.example()` or the panel.

The example operator does something useful on its own: "hard-surface prep" — shade smooth, add Smooth by Angle,
Bevel (by weight or angle) and Weighted Normal to every selected mesh, without duplicating existing modifiers.
Swap the body for your own task (topology linter, fastener placer, LOD generator, exporter...).
"""
import bpy, math
from bpy.props import FloatProperty, IntProperty, BoolProperty, EnumProperty

bl_info = {"name": "Model Helpers", "blender": (4, 2, 0), "category": "Mesh", "version": (0, 1, 0)}


def ensure_modifier(obj, name, kind):
    m = obj.modifiers.get(name)
    if m is None or m.type != kind:
        m = obj.modifiers.new(name, kind)
    return m


class MH_OT_example(bpy.types.Operator):
    """Prepare selected meshes for hard-surface shading (smooth + bevel + weighted normals)"""
    bl_idname = "model_helpers.example"
    bl_label = "Hard-Surface Prep"
    bl_options = {'REGISTER', 'UNDO'}

    width: FloatProperty(name="Bevel Width (m)", default=0.002, min=0.0, soft_max=0.1, precision=4)
    segments: IntProperty(name="Segments", default=2, min=1, max=16)
    limit: EnumProperty(name="Limit", items=[('ANGLE', "Angle", ""), ('WEIGHT', "Weight", "")], default='ANGLE')
    angle: FloatProperty(name="Angle", default=math.radians(30), subtype='ANGLE')
    weighted_normals: BoolProperty(name="Weighted Normal", default=True)

    @classmethod
    def poll(cls, context):
        return any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):
        done = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            for p in obj.data.polygons:
                p.use_smooth = True
            if not any(m.type == 'NODES' and 'Smooth by Angle' in m.name for m in obj.modifiers):
                try:  # Blender 4.1+: geometry-nodes based Smooth by Angle asset
                    with context.temp_override(object=obj, selected_objects=[obj], active_object=obj):
                        bpy.ops.object.modifier_add_node_group(
                            asset_library_type='ESSENTIALS', asset_library_identifier="",
                            relative_asset_identifier="geometry_nodes/smooth_by_angle.blend/NodeTree/Smooth by Angle")
                except Exception:
                    pass
            b = ensure_modifier(obj, "Bevel", 'BEVEL')
            b.width = self.width; b.segments = self.segments; b.limit_method = self.limit
            b.angle_limit = self.angle; b.harden_normals = True; b.use_clamp_overlap = True
            if self.weighted_normals:
                wn = ensure_modifier(obj, "WeightedNormal", 'WEIGHTED_NORMAL')
                wn.keep_sharp = True; wn.mode = 'FACE_AREA'
            done += 1
        self.report({'INFO'}, f"Prepared {done} mesh(es)")
        return {'FINISHED'}


class MH_PT_panel(bpy.types.Panel):
    bl_label = "Model Helpers"
    bl_idname = "MH_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Helpers"

    def draw(self, context):
        col = self.layout.column()
        col.operator(MH_OT_example.bl_idname, icon='MOD_BEVEL')


CLASSES = (MH_OT_example, MH_PT_panel)


def register():
    for c in CLASSES:
        try:
            bpy.utils.register_class(c)
        except ValueError:  # already registered — re-register for iteration
            bpy.utils.unregister_class(c); bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        try: bpy.utils.unregister_class(c)
        except RuntimeError: pass


if __name__ == "__main__" or True:  # executed via execute_blender_code → register immediately
    register()
    result = {"registered": [c.__name__ for c in CLASSES], "call": f"bpy.ops.{MH_OT_example.bl_idname}()"}
