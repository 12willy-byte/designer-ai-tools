# -*- coding: utf-8 -*-
import bpy, math, json, sys, os, colorsys

# Force CPU compute BEFORE any GPU access
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "NONE"
    prefs.get_devices()
    for dev in prefs.devices:
        dev.use = False
except Exception:
    pass

cfg = json.loads(os.environ.get("RENDER_CFG", '{"samples":8,"res_x":400,"res_y":300,"output":"render.png"}'))
cam = json.loads(os.environ.get("RENDER_CAM", '{"pos":[5,5,8],"tgt":[3,0,3]}'))
scene_d = json.loads(os.environ.get("RENDER_SCENE", '{"walls":[],"rooms":[],"furniture":[]}'))

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

sc = bpy.context.scene
# Force CYCLES CPU-only - safest for headless/no-GPU
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = min(cfg.get("samples", 4), 8)
sc.cycles.use_denoising = False
sc.cycles.use_adaptive_sampling = True
sc.cycles.adaptive_threshold = 0.05

sc.render.resolution_x = cfg["res_x"]
sc.render.resolution_y = cfg["res_y"]
sc.render.filepath = cfg["output"]
sc.render.image_settings.file_format = "PNG"

# Simple world
world = bpy.data.worlds.new("World") if not bpy.data.worlds else bpy.data.worlds[0]
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs["Strength"].default_value = 0.5

# Camera
scale = 0.001
cp = cam.get("position", [5, 5, 8])
bpy.ops.object.camera_add(location=(cp[0]*scale, cp[1]*scale, cp[2]*scale))
sc.camera = bpy.context.active_object

# Simple sun
bpy.ops.object.light_add(type="SUN", location=(10, 15, 8))
bpy.context.active_object.data.energy = 5

# Floor
bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
floor = bpy.context.active_object
floor_mat = bpy.data.materials.new("FloorMat")
floor_mat.use_nodes = True
floor_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.88, 0.86, 0.82, 1)
floor.data.materials.append(floor_mat)

# Walls
wall_mat = bpy.data.materials.new("WallMat")
wall_mat.use_nodes = True
wall_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.94, 0.93, 0.91, 1)

for w in scene_d.get("walls", []):
    sx = w["start"][0] * scale; sz = w["start"][2] * scale
    ex = w["end"][0] * scale; ez = w["end"][2] * scale
    h = w.get("h", 2800) * scale; t = w.get("t", 120) * scale
    dx = ex - sx; dz = ez - sz
    length = math.sqrt(dx*dx + dz*dz)
    if length < 0.001:
        continue
    mid_x = (sx + ex) / 2; mid_z = (sz + ez) / 2
    angle = math.atan2(dz, dx)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(mid_x, h/2, mid_z))
    obj = bpy.context.active_object
    obj.scale = (length, h, t)
    obj.rotation_euler = (0, 0, -angle)
    obj.data.materials.append(wall_mat)

# Furniture
for fi, f in enumerate(scene_d.get("furniture", [])):
    pos = f.get("pos", [0, 0, 0])
    px = pos[0] * scale; py = pos[1] * scale; pz = pos[2] * scale
    fw = f.get("w", 500) * scale; fd = f.get("d", 500) * scale; fh = f.get("h", 750) * scale
    bpy.ops.mesh.primitive_cube_add(size=1, location=(px, fh/2, pz))
    obj = bpy.context.active_object
    obj.scale = (fw, fh, fd)
    hue = (fi * 0.15 + 0.1) % 1.0
    r, g, b_val = colorsys.hsv_to_rgb(hue, 0.5, 0.85)
    fmat = bpy.data.materials.new("FurnMat_%d" % fi)
    fmat.use_nodes = True
    fmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (r, g, b_val, 1)
    obj.data.materials.append(fmat)

try:
    bpy.ops.render.render(write_still=True)
    if os.path.exists(cfg["output"]):
        print("RENDERED:" + cfg["output"])
    else:
        print("FAILED: no output")
except Exception as e:
    print("FAILED:" + str(e))
