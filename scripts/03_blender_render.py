import argparse
import csv
import json
import math
import shutil
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

CONFIG_JSON_PATH = Path(r"/home/cgna/km/Garment-Material-CLO-dataset/dataset_config.json")
SCRIPT_PATH = Path(globals().get("__file__", CONFIG_JSON_PATH.parent / "scripts" / "03_blender_render.py")).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent

repo_candidates = [
    SCRIPT_DIR,
    SCRIPT_DIR.parent,
    CONFIG_JSON_PATH.expanduser().resolve().parent,
]

REPO_ROOT = next(
    (
        p for p in repo_candidates
        if (p / "utils" / "blender_texture_mapping.py").exists()
    ),
    SCRIPT_DIR,
)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.blender_texture_mapping import (  # noqa: E402
    build_material as build_texture_mapped_material,
    discover_texture_files,
    parse_mtl_texture_refs,
    pick_textures,
)


def load_config(path):
    if not path:
        return {}
    path = Path(path).expanduser()
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def deep_get(obj, keys, default=None):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def require_config_value(config, keys):
    value = deep_get(config, keys, "")
    if value in (None, ""):
        raise ValueError(f"{'.'.join(keys)} is required in the config")
    return value


def resolve_path(value, base_dir):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def choose(cli_value, config, keys, default=None):
    if cli_value not in (None, ""):
        return cli_value
    return deep_get(config, keys, default)


def parse_bool(value, default=False):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def format_template(template, **values):
    try:
        return str(template).format(**values)
    except Exception:
        return str(template)


def derived_sample_dir_name(config, sample_index):
    fabric_template = require_config_value(config, ["naming", "fabric_file_template"])
    sample_template = require_config_value(config, ["naming", "sample_dir_template"])
    fabric_name = format_template(fabric_template, index=sample_index, index1=sample_index + 1)
    fabric_stem = Path(fabric_name).stem
    return format_template(
        sample_template,
        index=sample_index,
        index1=sample_index + 1,
        fabric_stem=fabric_stem,
        sample_name=fabric_stem,
    )


def resolve_texture_path(expected_path, obj_path, kind):
    if not expected_path:
        return None

    obj_path = Path(obj_path).expanduser()
    expected_path = Path(expected_path).expanduser()
    if not expected_path.is_absolute():
        expected_path = obj_path.parent / expected_path
    if expected_path.exists():
        return expected_path.resolve()

    patterns = (
        ["obj_diffuse*.png", "*BASE_rgb*.png", "*basecolor*.png", "*diffuse*.png", "*albedo*.png"]
        if kind == "diffuse"
        else ["obj_normal*.png", "*NRM*.png", "*normal*.png", "*bump*.png"]
    )
    for pattern in patterns:
        matches = sorted(expected_path.parent.glob(pattern))
        if matches:
            print(f"[Info] {kind} texture resolved: {expected_path} -> {matches[0]}")
            return matches[0].resolve()

    return expected_path.resolve()


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description="Render an OBJ into a COLMAP-style dataset from Blender."
    )
    parser.add_argument("--config", default="", help="Dataset config JSON path.")
    parser.add_argument(
        "--render_all_samples",
        default="",
        help="true renders every sample folder; false renders only sample_index.",
    )
    parser.add_argument("--sample_index", type=int, default=None, help="Sample index to render.")
    parser.add_argument("--obj_path", default="", help="Path to the OBJ mesh.")
    parser.add_argument(
        "--diffuse_path",
        default="",
        help="Path to the diffuse/albedo texture. Optional.",
    )
    parser.add_argument(
        "--normal_path",
        default="",
        help="Path to the tangent-space normal map. Optional.",
    )
    parser.add_argument(
        "--hdri_path",
        default="",
        help="Optional HDRI environment map for more photorealistic lighting.",
    )
    parser.add_argument(
        "--output_dir",
        default="",
        help="Output dataset directory. Example: blender_colmap_dataset_generated",
    )
    parser.add_argument("--num_views", type=int, default=None, help="Number of views.")
    parser.add_argument(
        "--resolution",
        type=int,
        default=None,
        help="Square render resolution in pixels.",
    )
    parser.add_argument(
        "--camera_radius",
        type=float,
        default=None,
        help="Explicit camera radius. If <= 0, radius is estimated automatically.",
    )
    parser.add_argument(
        "--radius_scale",
        type=float,
        default=None,
        help="Multiplier applied to the object bounding radius when camera_radius <= 0.",
    )
    parser.add_argument(
        "--lens_mm",
        type=float,
        default=None,
        help="Blender camera focal length in millimeters.",
    )
    parser.add_argument(
        "--sensor_width_mm",
        type=float,
        default=None,
        help="Camera sensor width in millimeters.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=None,
        help="Cycles samples per image.",
    )
    parser.add_argument(
        "--normal_strength",
        type=float,
        default=None,
        help="Normal map strength.",
    )
    parser.add_argument(
        "--world_strength",
        type=float,
        default=None,
        help="Background illumination strength.",
    )
    parser.add_argument(
        "--light_scale",
        type=float,
        default=None,
        help="Multiplier for all area light energies.",
    )
    parser.add_argument(
        "--exposure",
        type=float,
        default=None,
        help="Scene exposure adjustment for preserving texture detail.",
    )
    return parser.parse_args(argv)


def prepare_output_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    for subdir in (path / "images", path / "sparse"):
        if subdir.exists():
            shutil.rmtree(subdir)

    for file_name in ("camera_parameters.json", "mesh_vertices.csv", "dataset_summary.json"):
        file_path = path / file_name
        if file_path.exists():
            file_path.unlink()


def get_view3d_override():
    window = getattr(bpy.context, "window", None)
    screen = getattr(window, "screen", None) or getattr(bpy.context, "screen", None)
    if not screen:
        return {}

    base_override = {
        "window": window,
        "screen": screen,
        "scene": bpy.context.scene,
        "view_layer": bpy.context.view_layer,
    }

    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        region = next((item for item in area.regions if item.type == "WINDOW"), None)
        space = next((item for item in area.spaces if item.type == "VIEW_3D"), None)
        override = {
            **base_override,
            "area": area,
            "region": region,
            "space_data": space,
        }
        return {key: value for key, value in override.items() if value is not None}

    return {key: value for key, value in base_override.items() if value is not None}


def run_operator(operator, **kwargs):
    try:
        return operator(**kwargs)
    except RuntimeError as direct_error:
        override = get_view3d_override()
        if not override or not hasattr(bpy.context, "temp_override"):
            raise direct_error
        try:
            with bpy.context.temp_override(**override):
                return operator(**kwargs)
        except RuntimeError as override_error:
            raise RuntimeError(f"{direct_error}; with VIEW_3D override: {override_error}")


def deselect_all_objects():
    for obj in bpy.context.scene.objects:
        obj.select_set(False)


def reset_scene():
    scene = bpy.context.scene
    deselect_all_objects()

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    for collection in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.images,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for item in list(collection):
            if item.users == 0:
                collection.remove(item)

    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    return scene


def import_obj(obj_path):
    existing = set(obj.name for obj in bpy.data.objects)

    errors = []
    imported_ok = False

    if hasattr(bpy.ops.wm, "obj_import"):
        try:
            run_operator(bpy.ops.wm.obj_import, filepath=str(obj_path))
            imported_ok = True
        except Exception as exc:
            errors.append(f"wm.obj_import failed: {exc}")

    if not imported_ok:
        try:
            bpy.ops.preferences.addon_enable(module="io_scene_obj")
        except Exception as exc:
            errors.append(f"enable io_scene_obj failed: {exc}")

        if hasattr(bpy.ops.import_scene, "obj"):
            try:
                run_operator(bpy.ops.import_scene.obj, filepath=str(obj_path))
                imported_ok = True
            except Exception as exc:
                errors.append(f"import_scene.obj failed: {exc}")

    if not imported_ok:
        raise RuntimeError("OBJ import failed. " + " | ".join(errors))

    imported = [obj for obj in bpy.data.objects if obj.name not in existing]
    mesh_objects = [obj for obj in imported if obj.type == "MESH"]

    if not mesh_objects:
        raise RuntimeError("No mesh objects were imported from the OBJ file.")

    deselect_all_objects()
    for obj in mesh_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objects[0]

    if len(mesh_objects) > 1:
        run_operator(bpy.ops.object.join)
        mesh_obj = bpy.context.view_layer.objects.active
    else:
        mesh_obj = mesh_objects[0]

    run_operator(bpy.ops.object.transform_apply, location=False, rotation=True, scale=True)
    return mesh_obj


def compute_bounds_world(obj):
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_corner = Vector(
        (
            min(v.x for v in corners),
            min(v.y for v in corners),
            min(v.z for v in corners),
        )
    )
    max_corner = Vector(
        (
            max(v.x for v in corners),
            max(v.y for v in corners),
            max(v.z for v in corners),
        )
    )
    center = (min_corner + max_corner) * 0.5
    size = max_corner - min_corner
    return min_corner, max_corner, center, size


def center_mesh_at_origin(obj):
    _, _, center, _ = compute_bounds_world(obj)
    obj.location -= center
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    run_operator(bpy.ops.object.transform_apply, location=True, rotation=False, scale=False)
    obj.select_set(False)


def configure_mesh_shading(obj):
    deselect_all_objects()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    run_operator(bpy.ops.object.shade_smooth)
    if hasattr(obj.data, "use_auto_smooth"):
        obj.data.use_auto_smooth = True
        obj.data.auto_smooth_angle = math.radians(180.0)
    obj.select_set(False)


def build_material(diffuse_path, normal_path, normal_strength):
    material = bpy.data.materials.new(name="OBJ_PBR")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (500, 0)
    principled = nodes.new(type="ShaderNodeBsdfPrincipled")
    principled.location = (180, 0)
    principled.inputs["Roughness"].default_value = 0.45
    if "Specular IOR Level" in principled.inputs:
        principled.inputs["Specular IOR Level"].default_value = 0.5
    elif "Specular" in principled.inputs:
        principled.inputs["Specular"].default_value = 0.5

    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    if diffuse_path and Path(diffuse_path).exists():
        tex = nodes.new(type="ShaderNodeTexImage")
        tex.location = (-420, 120)
        tex.image = bpy.data.images.load(str(diffuse_path), check_existing=True)
        tex.image.colorspace_settings.name = "sRGB"
        links.new(tex.outputs["Color"], principled.inputs["Base Color"])

    if normal_path and Path(normal_path).exists():
        normal_tex = nodes.new(type="ShaderNodeTexImage")
        normal_tex.location = (-420, -150)
        normal_tex.image = bpy.data.images.load(str(normal_path), check_existing=True)
        normal_tex.image.colorspace_settings.name = "Non-Color"

        normal_map = nodes.new(type="ShaderNodeNormalMap")
        normal_map.location = (-120, -150)
        normal_map.inputs["Strength"].default_value = normal_strength

        links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])

    return material


def build_material_from_obj_dir(obj_path, explicit_diffuse_path, explicit_normal_path, normal_strength):
    obj_dir = Path(obj_path).parent
    mtl_path = Path(obj_path).with_suffix(".mtl")
    texture_paths = discover_texture_files(obj_dir)
    mtl_refs = parse_mtl_texture_refs(mtl_path, obj_dir)
    textures = pick_textures(texture_paths, mtl_refs)

    if explicit_diffuse_path:
        textures["diffuse"] = Path(explicit_diffuse_path).expanduser().resolve()
    if explicit_normal_path:
        textures["normal"] = Path(explicit_normal_path).expanduser().resolve()

    material, loaded_textures = build_texture_mapped_material(
        textures,
        normal_strength=normal_strength,
    )
    return material, {
        "mtl_path": str(mtl_path) if mtl_path.exists() else "",
        "texture_files": [str(path) for path in texture_paths],
        "mtl_refs": {key: str(value) for key, value in mtl_refs.items()},
        "selected_textures": {
            key: ([str(item) for item in value] if isinstance(value, list) else (str(value) if value else ""))
            for key, value in textures.items()
        },
        "loaded_textures": loaded_textures,
    }


def material_uses_image_textures(material):
    if material is None or not material.use_nodes:
        return False
    for node in material.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and getattr(node, "image", None):
            return True
    return False


def imported_materials_use_textures(obj):
    return any(material_uses_image_textures(material) for material in obj.data.materials)


def assign_material(obj, material):
    obj.data.materials.clear()
    obj.data.materials.append(material)


def create_area_light(name, location, size, energy):
    light_data = bpy.data.lights.new(name=name, type="AREA")
    light_data.shape = "DISK"
    light_data.energy = energy
    light_data.size = size
    light = bpy.data.objects.new(name, light_data)
    bpy.context.collection.objects.link(light)
    light.location = Vector(location)
    look_at(light, Vector((0.0, 0.0, 0.0)))
    return light


def get_or_create_world_background(world):
    nodes = world.node_tree.nodes
    links = world.node_tree.links

    bg = next((node for node in nodes if node.bl_idname == "ShaderNodeBackground"), None)
    if bg is None:
        bg = nodes.new(type="ShaderNodeBackground")
        bg.location = (0, 0)

    output = next((node for node in nodes if node.bl_idname == "ShaderNodeOutputWorld"), None)
    if output is None:
        output = nodes.new(type="ShaderNodeOutputWorld")
        output.location = (260, 0)

    has_world_link = any(
        link.from_node == bg
        and link.to_node == output
        and link.to_socket == output.inputs["Surface"]
        for link in links
    )
    if not has_world_link:
        links.new(bg.outputs[0], output.inputs["Surface"])

    return bg


def setup_soft_lighting(scene, object_radius, world_strength, light_scale, hdri_path=None):
    world = bpy.data.worlds.new("DatasetWorld")
    scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    bg = get_or_create_world_background(world)
    bg.inputs["Strength"].default_value = world_strength

    if hdri_path and Path(hdri_path).exists():
        env = nodes.new(type="ShaderNodeTexEnvironment")
        env.location = (-320, 0)
        env.image = bpy.data.images.load(str(hdri_path), check_existing=True)
        links.new(env.outputs["Color"], bg.inputs["Color"])
    else:
        bg.inputs["Color"].default_value = (0.82, 0.84, 0.87, 1.0)

    light_radius = max(object_radius * 3.8, 1.0)
    light_size = max(object_radius * 5.5, 2.0)
    hdri_scale = 0.65 if hdri_path else 1.0
    base_energy = 2500.0 * max(object_radius, 0.25) * hdri_scale * light_scale

    positions = [
        (light_radius, 0.0, light_radius * 0.45),
        (-light_radius, 0.0, light_radius * 0.45),
        (0.0, light_radius, light_radius * 0.45),
        (0.0, -light_radius, light_radius * 0.45),
        (0.0, 0.0, light_radius),
        (light_radius * 0.35, light_radius * 0.35, -light_radius * 0.2),
    ]
    energies = [
        base_energy * 0.85,
        base_energy * 0.85,
        base_energy * 0.55,
        base_energy * 0.55,
        base_energy * 0.75,
        base_energy * 0.35,
    ]

    for index, (position, energy) in enumerate(zip(positions, energies), start=1):
        create_area_light(
            name=f"AreaLight_{index}",
            location=position,
            size=light_size,
            energy=energy,
        )


def configure_cycles(scene, samples, exposure):
    scene.render.engine = "CYCLES"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    if hasattr(scene.render.image_settings, "alpha_mode"):
        scene.render.image_settings.alpha_mode = "STRAIGHT"
    scene.render.film_transparent = True
    scene.cycles.samples = samples
    scene.cycles.preview_samples = min(samples, 64)
    scene.cycles.use_adaptive_sampling = True

    if hasattr(scene.cycles, "use_denoising"):
        scene.cycles.use_denoising = True
    if hasattr(scene.cycles, "use_auto_tile"):
        scene.cycles.use_auto_tile = True
    if hasattr(scene.cycles, "max_bounces"):
        scene.cycles.max_bounces = 12
        scene.cycles.diffuse_bounces = 4
        scene.cycles.glossy_bounces = 4
        scene.cycles.transparent_max_bounces = 8

    scene.render.resolution_percentage = 100

    try:
        scene.view_settings.view_transform = "Filmic"
        scene.view_settings.look = "Medium High Contrast"
        scene.view_settings.exposure = exposure
    except Exception:
        pass

    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        selected_device = None
        for device_type in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                prefs.compute_device_type = device_type
                prefs.get_devices()
                if any(device.type != "CPU" for device in prefs.devices):
                    selected_device = device_type
                    break
            except Exception:
                continue

        if selected_device:
            scene.cycles.device = "GPU"
            for device in prefs.devices:
                device.use = True
            print(f"[Info] Cycles device: GPU ({selected_device})")
        else:
            scene.cycles.device = "CPU"
            print("[Info] Cycles device: CPU")
    except Exception as exc:
        scene.cycles.device = "CPU"
        print(f"[Warning] Failed to configure GPU rendering: {exc}")


def setup_camera(scene, resolution, lens_mm, sensor_width_mm):
    cam_data = bpy.data.cameras.new("RenderCamera")
    cam_data.type = "PERSP"
    cam_data.lens = lens_mm
    cam_data.sensor_width = sensor_width_mm
    cam_data.sensor_height = sensor_width_mm
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.clip_start = 0.01
    cam_data.clip_end = 10000.0

    cam_obj = bpy.data.objects.new("RenderCamera", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0
    return cam_obj


def fibonacci_sphere(samples, radius):
    if samples <= 0:
        return []
    if samples == 1:
        return [Vector((0.0, -radius, 0.0))]

    points = []
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(samples):
        y = 1.0 - (2.0 * i) / (samples - 1)
        r = math.sqrt(max(0.0, 1.0 - y * y))
        theta = golden_angle * i
        x = math.cos(theta) * r
        z = math.sin(theta) * r
        points.append(Vector((x * radius, y * radius, z * radius)))
    return points


def look_at(obj, target):
    location = obj.location.copy()
    forward = (target - location).normalized()
    up_guess = Vector((0.0, 0.0, 1.0))
    if abs(forward.dot(up_guess)) > 0.999:
        up_guess = Vector((0.0, 1.0, 0.0))

    right = forward.cross(up_guess).normalized()
    up = right.cross(forward).normalized()
    rotation = Matrix((right, up, -forward)).transposed().to_4x4()
    obj.matrix_world = Matrix.Translation(location) @ rotation


def compute_object_radius(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    radius = 0.0
    for vertex in mesh.vertices:
        world_vertex = evaluated.matrix_world @ vertex.co
        radius = max(radius, world_vertex.length)
    evaluated.to_mesh_clear()
    return max(radius, 1e-6)


def compute_intrinsics(camera, scene):
    scale = scene.render.resolution_percentage / 100.0
    width = scene.render.resolution_x * scale
    height = scene.render.resolution_y * scale
    sensor_width = camera.data.sensor_width
    sensor_height = camera.data.sensor_height

    if camera.data.sensor_fit == "VERTICAL":
        su = width / sensor_width / (scene.render.pixel_aspect_x / scene.render.pixel_aspect_y)
        sv = height / sensor_height
    else:
        su = width / sensor_width
        sv = height / sensor_height

    fx = camera.data.lens * su
    fy = camera.data.lens * sv
    cx = width * 0.5 - camera.data.shift_x * width
    cy = height * 0.5 + camera.data.shift_y * height

    return {
        "width": int(width),
        "height": int(height),
        "fx": float(fx),
        "fy": float(fy),
        "cx": float(cx),
        "cy": float(cy),
    }


def matrix_to_list(matrix):
    return [[float(value) for value in row] for row in matrix]


def blender_to_colmap_world_to_camera(camera):
    blender_world_to_camera = camera.matrix_world.inverted()
    blender_cam_to_colmap_cam = Matrix(
        (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, -1.0, 0.0, 0.0),
            (0.0, 0.0, -1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    return blender_cam_to_colmap_cam @ blender_world_to_camera


def collect_vertex_rows(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()

    normal_matrix = evaluated.matrix_world.to_3x3().inverted().transposed()
    rows = []
    for vertex in mesh.vertices:
        world_pos = evaluated.matrix_world @ vertex.co
        world_normal = (normal_matrix @ vertex.normal).normalized()
        rows.append(
            {
                "id": int(vertex.index),
                "x": float(world_pos.x),
                "y": float(world_pos.y),
                "z": float(world_pos.z),
                "nx": float(world_normal.x),
                "ny": float(world_normal.y),
                "nz": float(world_normal.z),
            }
        )

    evaluated.to_mesh_clear()
    return rows


def write_binary_ply(path, vertices):
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {len(vertices)}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property float nx\n"
        "property float ny\n"
        "property float nz\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    ).encode("ascii")

    with open(path, "wb") as handle:
        handle.write(header)
        for row in vertices:
            handle.write(
                struct.pack(
                    "<ffffffBBB",
                    row["x"],
                    row["y"],
                    row["z"],
                    row["nx"],
                    row["ny"],
                    row["nz"],
                    255,
                    255,
                    255,
                )
            )


def write_vertex_csv(path, vertices):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["vertex_id", "x", "y", "z", "nx", "ny", "nz"])
        for row in vertices:
            writer.writerow(
                [row["id"], row["x"], row["y"], row["z"], row["nx"], row["ny"], row["nz"]]
            )


def render_views(scene, camera, output_dir, view_positions, intrinsics):
    image_dir = Path(output_dir) / "images"
    sparse_dir = Path(output_dir) / "sparse" / "0"
    image_dir.mkdir(parents=True, exist_ok=True)
    sparse_dir.mkdir(parents=True, exist_ok=True)

    camera_json = {
        "camera_model": "PINHOLE",
        "intrinsics": intrinsics,
        "images": [],
    }
    images_txt_lines = [
        "# Image list with two lines of data per image:",
        "#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME",
        "#   POINTS2D[] as (X, Y, POINT3D_ID)",
        f"# Number of images: {len(view_positions)}, mean observations per image: 0",
    ]

    for index, position in enumerate(view_positions):
        camera.location = position
        look_at(camera, Vector((0.0, 0.0, 0.0)))
        bpy.context.view_layer.update()

        file_name = f"{index:04d}.png"
        scene.render.filepath = str(image_dir / file_name)
        bpy.ops.render.render(write_still=True)

        blender_world_to_camera = camera.matrix_world.inverted()
        world_to_camera = blender_to_colmap_world_to_camera(camera)
        rotation = world_to_camera.to_3x3()
        translation = world_to_camera.translation
        quaternion = rotation.to_quaternion()

        images_txt_lines.append(
            (
                f"{index + 1} "
                f"{quaternion.w:.16f} {quaternion.x:.16f} {quaternion.y:.16f} {quaternion.z:.16f} "
                f"{translation.x:.16f} {translation.y:.16f} {translation.z:.16f} "
                f"1 {file_name}"
            )
        )
        images_txt_lines.append("")

        camera_json["images"].append(
            {
                "image_id": index + 1,
                "file_name": file_name,
                "camera_id": 1,
                "camera_center_world": [float(v) for v in camera.location],
                "quaternion_wxyz_world_to_camera": [
                    float(quaternion.w),
                    float(quaternion.x),
                    float(quaternion.y),
                    float(quaternion.z),
                ],
                "translation_world_to_camera": [
                    float(translation.x),
                    float(translation.y),
                    float(translation.z),
                ],
                "world_to_camera": matrix_to_list(world_to_camera),
                "blender_world_to_camera": matrix_to_list(blender_world_to_camera),
                "camera_to_world": matrix_to_list(camera.matrix_world),
            }
        )

    cameras_txt = (
        "# Camera list with one line of data per camera:\n"
        "#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n"
        "# Number of cameras: 1\n"
        f"1 PINHOLE {intrinsics['width']} {intrinsics['height']} "
        f"{intrinsics['fx']:.16f} {intrinsics['fy']:.16f} "
        f"{intrinsics['cx']:.16f} {intrinsics['cy']:.16f}\n"
    )

    with open(sparse_dir / "cameras.txt", "w", encoding="utf-8") as handle:
        handle.write(cameras_txt)
    with open(sparse_dir / "images.txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(images_txt_lines) + "\n")
    with open(sparse_dir / "points3D.txt", "w", encoding="utf-8") as handle:
        handle.write("")
    with open(sparse_dir / "project.ini", "w", encoding="utf-8") as handle:
        handle.write("")
    with open(Path(output_dir) / "camera_parameters.json", "w", encoding="utf-8") as handle:
        json.dump(camera_json, handle, indent=2)


def render_one_sample(target, render_settings):
    sample_name = target.get("sample_name", "")
    sample_index = target.get("sample_index")
    obj_path = Path(target["obj_path"]).expanduser().resolve()
    diffuse_path_value = target.get("diffuse_path", "")
    normal_path_value = target.get("normal_path", "")
    hdri_path_value = render_settings.get("hdri_path", "")
    output_dir = Path(target["output_dir"]).expanduser().resolve()

    if not obj_path.exists():
        raise FileNotFoundError(f"OBJ file not found: {obj_path}")

    diffuse_path = resolve_texture_path(diffuse_path_value, obj_path, "diffuse") if diffuse_path_value else None
    normal_path = resolve_texture_path(normal_path_value, obj_path, "normal") if normal_path_value else None
    hdri_path = Path(hdri_path_value).expanduser().resolve() if hdri_path_value else None

    if diffuse_path_value and diffuse_path and not diffuse_path.exists():
        raise FileNotFoundError(
            f"Diffuse texture not found: {diffuse_path}. "
            f"Expected it under {obj_path.parent}."
        )
    if normal_path_value and normal_path and not normal_path.exists():
        raise FileNotFoundError(
            f"Normal map not found: {normal_path}. "
            f"Expected it under {obj_path.parent}."
        )
    if hdri_path and not hdri_path.exists():
        raise FileNotFoundError(f"HDRI file not found: {hdri_path}")

    print("=" * 80)
    print(f"[Render] {sample_name or obj_path.parent.name}")
    print(f"  obj    : {obj_path}")
    print(f"  output : {output_dir}")

    prepare_output_dir(output_dir)

    scene = reset_scene()
    mesh_obj = import_obj(obj_path)
    center_mesh_at_origin(mesh_obj)
    configure_mesh_shading(mesh_obj)

    if imported_materials_use_textures(mesh_obj) and not diffuse_path and not normal_path:
        texture_report = {
            "mode": "use_imported_obj_mtl_materials",
            "mtl_path": str(Path(obj_path).with_suffix(".mtl"))
            if Path(obj_path).with_suffix(".mtl").exists()
            else "",
            "material_names": [mat.name for mat in mesh_obj.data.materials],
            "material_count": len(mesh_obj.data.materials),
            "uv_layers": [uv.name for uv in mesh_obj.data.uv_layers],
            "loaded_textures": {},
        }
    else:
        material, texture_report = build_material_from_obj_dir(
            obj_path,
            diffuse_path,
            normal_path,
            render_settings["normal_strength"],
        )
        assign_material(mesh_obj, material)
        texture_report["mode"] = (
            "fallback_texture_mapping"
            if not diffuse_path and not normal_path
            else "explicit_texture_mapping"
        )
        texture_report["material_names"] = [mat.name for mat in mesh_obj.data.materials]
        texture_report["material_count"] = len(mesh_obj.data.materials)
        texture_report["uv_layers"] = [uv.name for uv in mesh_obj.data.uv_layers]

    object_radius = compute_object_radius(mesh_obj)
    camera_radius_arg = render_settings["camera_radius"]
    camera_radius = (
        camera_radius_arg if camera_radius_arg > 0.0 else object_radius * render_settings["radius_scale"]
    )
    print(f"[Info] object radius={object_radius:.6f}, camera radius={camera_radius:.6f}")

    configure_cycles(scene, render_settings["samples"], render_settings["exposure"])
    setup_soft_lighting(
        scene,
        object_radius,
        render_settings["world_strength"],
        render_settings["light_scale"],
        hdri_path=hdri_path,
    )
    camera = setup_camera(
        scene,
        render_settings["resolution"],
        render_settings["lens_mm"],
        render_settings["sensor_width_mm"],
    )
    intrinsics = compute_intrinsics(camera, scene)

    view_positions = fibonacci_sphere(render_settings["num_views"], camera_radius)
    render_views(scene, camera, output_dir, view_positions, intrinsics)

    vertices = collect_vertex_rows(mesh_obj)
    sparse_dir = output_dir / "sparse" / "0"
    write_binary_ply(sparse_dir / "points3D.ply", vertices)
    write_vertex_csv(output_dir / "mesh_vertices.csv", vertices)

    summary = {
        "sample_index": sample_index,
        "sample_name": sample_name,
        "obj_path": str(obj_path),
        "diffuse_path": texture_report.get("loaded_textures", {}).get("diffuse", ""),
        "normal_path": texture_report.get("loaded_textures", {}).get("normal", ""),
        "texture_mapping": texture_report,
        "hdri_path": str(hdri_path) if hdri_path else "",
        "output_dir": str(output_dir),
        "num_views": render_settings["num_views"],
        "resolution": render_settings["resolution"],
        "samples": render_settings["samples"],
        "world_strength": render_settings["world_strength"],
        "light_scale": render_settings["light_scale"],
        "exposure": render_settings["exposure"],
        "object_radius": object_radius,
        "camera_radius": camera_radius,
        "intrinsics": intrinsics,
        "vertex_count": len(vertices),
        "output_files": {
            "images_dir": str(output_dir / "images"),
            "camera_parameters_json": str(output_dir / "camera_parameters.json"),
            "colmap_cameras_txt": str(sparse_dir / "cameras.txt"),
            "colmap_images_txt": str(sparse_dir / "images.txt"),
            "colmap_points3d_txt": str(sparse_dir / "points3D.txt"),
            "geometry_ply": str(sparse_dir / "points3D.ply"),
            "mesh_vertices_csv": str(output_dir / "mesh_vertices.csv"),
            "summary_json": str(output_dir / "dataset_summary.json"),
        },
    }
    with open(output_dir / "dataset_summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)

    print("[Done] Dataset written to:", output_dir)
    return summary


def sample_index_from_dir_name(name, fallback):
    prefix = str(name).split("_", 1)[0]
    try:
        return int(prefix)
    except ValueError:
        return fallback


def discover_render_targets(obj_root, render_root, obj_file_name):
    if not obj_root.exists():
        raise FileNotFoundError(f"OBJ root not found: {obj_root}")

    targets = []
    for obj_path in sorted(obj_root.rglob(obj_file_name)):
        sample_dir = obj_path.parent
        rel_dir = sample_dir.relative_to(obj_root)
        sample_name = "__".join(rel_dir.parts)
        if not sample_name:
            sample_name = sample_dir.name
        sample_index = sample_index_from_dir_name(rel_dir.parts[-1], len(targets)) if rel_dir.parts else len(targets)
        targets.append(
            {
                "sample_index": sample_index,
                "sample_name": sample_name,
                "obj_path": str(obj_path),
                "diffuse_path": "",
                "normal_path": "",
                "output_dir": str(render_root / rel_dir),
            }
        )

    if not targets:
        raise RuntimeError(f"No sample folders with {obj_file_name} found in {obj_root}")
    return targets


def write_pipeline_summary(path, summary):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)


def main():
    args = parse_args()

    config_path = Path(args.config or CONFIG_JSON_PATH).expanduser().resolve()
    config = load_config(config_path)
    config_dir = config_path.parent
    output_root = (
        deep_get(config, ["project", "output_dir"])
        or deep_get(config, ["project", "dataset_root"])
        or ""
    )
    if not output_root:
        raise ValueError("project.output_dir is required in the config")
    output_root_path = resolve_path(output_root, config_dir)

    obj_root = output_root_path / require_config_value(config, ["naming", "draped_dir"])
    render_root = output_root_path / require_config_value(config, ["naming", "render_dir"])
    obj_file_name = require_config_value(config, ["naming", "obj_file"])

    render_all_samples = parse_bool(
        choose(
            args.render_all_samples,
            config,
            ["blender_render", "render_all_samples"],
            True,
        ),
        True,
    )
    sample_index = int(
        choose(args.sample_index, config, ["blender_render", "sample_index"], 0)
    )

    hdri_path_value = (
        args.hdri_path
        or deep_get(config, ["stage_3_blender_render", "inputs", "hdri_path"], "")
        or deep_get(config, ["stage_4_blender_render", "inputs", "hdri_path"], "")
        or deep_get(config, ["blender_render", "hdri_path"], "")
    )
    render_settings = {
        "hdri_path": hdri_path_value,
        "num_views": int(choose(args.num_views, config, ["stage_3_blender_render", "settings", "num_views"], deep_get(config, ["stage_4_blender_render", "settings", "num_views"], deep_get(config, ["blender_render", "num_views"], 24)))),
        "resolution": int(choose(args.resolution, config, ["stage_3_blender_render", "settings", "resolution"], deep_get(config, ["stage_4_blender_render", "settings", "resolution"], deep_get(config, ["blender_render", "resolution"], 1080)))),
        "camera_radius": float(choose(args.camera_radius, config, ["stage_3_blender_render", "settings", "camera_radius"], deep_get(config, ["stage_4_blender_render", "settings", "camera_radius"], deep_get(config, ["blender_render", "camera_radius"], 0.0)))),
        "radius_scale": float(choose(args.radius_scale, config, ["stage_3_blender_render", "settings", "radius_scale"], deep_get(config, ["stage_4_blender_render", "settings", "radius_scale"], deep_get(config, ["blender_render", "radius_scale"], 4.0)))),
        "lens_mm": float(choose(args.lens_mm, config, ["stage_3_blender_render", "settings", "lens_mm"], deep_get(config, ["stage_4_blender_render", "settings", "lens_mm"], deep_get(config, ["blender_render", "lens_mm"], 50.0)))),
        "sensor_width_mm": float(choose(args.sensor_width_mm, config, ["stage_3_blender_render", "settings", "sensor_width_mm"], deep_get(config, ["stage_4_blender_render", "settings", "sensor_width_mm"], deep_get(config, ["blender_render", "sensor_width_mm"], 36.0)))),
        "samples": int(choose(args.samples, config, ["stage_3_blender_render", "settings", "samples"], deep_get(config, ["stage_4_blender_render", "settings", "samples"], deep_get(config, ["blender_render", "samples"], 256)))),
        "normal_strength": float(choose(args.normal_strength, config, ["stage_3_blender_render", "settings", "normal_strength"], deep_get(config, ["stage_4_blender_render", "settings", "normal_strength"], deep_get(config, ["blender_render", "normal_strength"], 1.0)))),
        "world_strength": float(choose(args.world_strength, config, ["stage_3_blender_render", "settings", "world_strength"], deep_get(config, ["stage_4_blender_render", "settings", "world_strength"], deep_get(config, ["blender_render", "world_strength"], 0.2)))),
        "light_scale": float(choose(args.light_scale, config, ["stage_3_blender_render", "settings", "light_scale"], deep_get(config, ["stage_4_blender_render", "settings", "light_scale"], deep_get(config, ["blender_render", "light_scale"], 0.12)))),
        "exposure": float(choose(args.exposure, config, ["stage_3_blender_render", "settings", "exposure"], deep_get(config, ["stage_4_blender_render", "settings", "exposure"], deep_get(config, ["blender_render", "exposure"], -0.2)))),
    }

    explicit_obj_path = choose(args.obj_path, config, ["stage_3_blender_render", "inputs", "obj_path"], deep_get(config, ["stage_4_blender_render", "inputs", "obj_path"], ""))
    explicit_output_dir = choose(args.output_dir, config, ["stage_3_blender_render", "outputs", "render_dir"], deep_get(config, ["stage_4_blender_render", "outputs", "render_dir"], ""))
    explicit_diffuse_path = choose(args.diffuse_path, config, ["stage_3_blender_render", "inputs", "diffuse_path"], deep_get(config, ["stage_4_blender_render", "inputs", "diffuse_path"], ""))
    explicit_normal_path = choose(args.normal_path, config, ["stage_3_blender_render", "inputs", "normal_path"], deep_get(config, ["stage_4_blender_render", "inputs", "normal_path"], ""))

    render_root.mkdir(parents=True, exist_ok=True)
    pipeline_summary_path = render_root / "pipeline_summary.json"

    if explicit_obj_path or explicit_output_dir:
        sample_dir_name = derived_sample_dir_name(config, sample_index)
        sample_obj_dir = obj_root / sample_dir_name
        obj_path = explicit_obj_path or str(sample_obj_dir / obj_file_name)
        output_dir = explicit_output_dir or str(render_root / sample_dir_name)
        targets = [
            {
                "sample_index": sample_index,
                "sample_name": sample_dir_name,
                "obj_path": obj_path,
                "diffuse_path": explicit_diffuse_path,
                "normal_path": explicit_normal_path,
                "output_dir": output_dir,
            }
        ]
    elif render_all_samples:
        targets = discover_render_targets(
            obj_root,
            render_root,
            obj_file_name,
        )
    else:
        all_targets = discover_render_targets(
            obj_root,
            render_root,
            obj_file_name,
        )
        matches = [target for target in all_targets if target["sample_index"] == sample_index]
        if not matches:
            raise RuntimeError(f"No render sample matched sample_index={sample_index}")
        targets = matches[:1]
        targets[0]["diffuse_path"] = explicit_diffuse_path
        targets[0]["normal_path"] = explicit_normal_path

    pipeline_summary = {
        "render_all_samples": render_all_samples,
        "obj_root": str(obj_root),
        "render_root": str(render_root),
        "num_targets": len(targets),
        "samples": [],
        "output_files": {
            "render_root": str(render_root),
            "pipeline_summary_json": str(pipeline_summary_path),
        },
    }
    write_pipeline_summary(pipeline_summary_path, pipeline_summary)

    for target in targets:
        sample_record = {
            "sample_index": target.get("sample_index"),
            "sample_name": target.get("sample_name"),
            "obj_path": target.get("obj_path"),
            "output_dir": target.get("output_dir"),
            "status": "started",
        }
        pipeline_summary["samples"].append(sample_record)
        write_pipeline_summary(pipeline_summary_path, pipeline_summary)

        try:
            sample_summary = render_one_sample(target, render_settings)
            sample_record.update(
                {
                    "status": "success",
                    "summary_json": sample_summary["output_files"]["summary_json"],
                    "images_dir": sample_summary["output_files"]["images_dir"],
                    "geometry_ply": sample_summary["output_files"]["geometry_ply"],
                }
            )
        except Exception as exc:
            sample_record.update({"status": "failed", "error": str(exc)})
            write_pipeline_summary(pipeline_summary_path, pipeline_summary)
            raise

        write_pipeline_summary(pipeline_summary_path, pipeline_summary)

    print("[Done] Rendered samples:", len(targets))
    print("[Done] Pipeline summary:", pipeline_summary_path)


if __name__ == "__main__":
    main()
