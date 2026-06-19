import argparse
import json
import math
import os
from pathlib import Path

import bpy
from mathutils import Vector


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = SCRIPT_DIR / "clo_obj_export"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".exr"}
GENERATED_FILE_PREFIXES = ("texture_mapping_",)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Import a CLO OBJ export into Blender and map all texture files."
    )
    parser.add_argument(
        "--input_dir",
        default=str(DEFAULT_INPUT_DIR),
        help="Directory containing CLO OBJ/MTL/texture export files.",
    )
    parser.add_argument("--obj", default="", help="OBJ path. Defaults to the first OBJ in input_dir.")
    parser.add_argument(
        "--render_path",
        default="",
        help="Preview render path. Defaults to input_dir/texture_mapping_preview.png.",
    )
    parser.add_argument(
        "--blend_path",
        default="",
        help="Optional .blend output path. Defaults to input_dir/texture_mapping.blend.",
    )
    parser.add_argument("--resolution", type=int, default=1024, help="Preview render resolution.")
    parser.add_argument("--normal_strength", type=float, default=1.0, help="Normal map strength.")
    parser.add_argument("--bump_strength", type=float, default=0.06, help="Displacement-as-bump strength.")
    parser.add_argument("--cycles_samples", type=int, default=96, help="Cycles render samples.")

    argv = []
    if "--" in os.sys.argv:
        argv = os.sys.argv[os.sys.argv.index("--") + 1 :]
    return parser.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for collection in (bpy.data.materials, bpy.data.images, bpy.data.textures):
        for item in list(collection):
            collection.remove(item)


def ensure_path(path):
    return Path(path).expanduser().resolve()


def discover_obj(input_dir, explicit_obj=""):
    if explicit_obj:
        obj_path = ensure_path(explicit_obj)
        if obj_path.exists():
            return obj_path
        raise FileNotFoundError(f"OBJ file does not exist: {obj_path}")

    obj_files = sorted(input_dir.glob("*.obj"))
    if not obj_files:
        raise FileNotFoundError(f"No OBJ file found in {input_dir}")
    return obj_files[0]


def local_texture_path(raw_path, input_dir):
    if not raw_path:
        return None

    cleaned = raw_path.strip().strip('"')
    if not cleaned:
        return None

    direct = Path(cleaned)
    local = input_dir / direct.name
    if local.exists():
        return local.resolve()

    if direct.exists():
        return direct.resolve()

    return None


def parse_mtl_texture_refs(mtl_path, input_dir):
    refs = {}
    if not mtl_path or not mtl_path.exists():
        return refs

    for line in mtl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(maxsplit=1)
        if len(parts) != 2:
            continue
        key = parts[0].lower()
        if key not in {"map_ka", "map_kd", "map_bump", "bump", "map_normal", "norm", "map_pr", "map_pm"}:
            continue
        path = local_texture_path(parts[1], input_dir)
        if path:
            refs.setdefault(key, path)
    return refs


def discover_texture_files(input_dir):
    return sorted(
        path.resolve()
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        and not path.name.lower().startswith(GENERATED_FILE_PREFIXES)
    )


def classify_texture(path):
    name = path.stem.lower()
    if any(token in name for token in ("base_rgb", "basecolor", "base_color", "diffuse", "albedo", "color")):
        return "diffuse"
    if any(token in name for token in ("_nrm", "normal", "norm")):
        return "normal"
    if any(token in name for token in ("rough", "roughness")):
        return "roughness"
    if any(token in name for token in ("_mtl", "metal", "metallic", "metalness")):
        return "metallic"
    if any(token in name for token in ("disp", "displacement", "height")):
        return "displacement"
    if any(token in name for token in ("opacity", "alpha", "transparent")):
        return "alpha"
    return "extra"


def pick_textures(texture_paths, mtl_refs):
    by_role = {
        "diffuse": None,
        "normal": None,
        "roughness": None,
        "metallic": None,
        "displacement": None,
        "alpha": None,
        "extra": [],
    }

    if "map_kd" in mtl_refs:
        by_role["diffuse"] = mtl_refs["map_kd"]
    elif "map_ka" in mtl_refs:
        by_role["diffuse"] = mtl_refs["map_ka"]

    for key in ("map_normal", "norm", "map_bump", "bump"):
        if key in mtl_refs:
            by_role["normal"] = mtl_refs[key]
            break

    for path in texture_paths:
        role = classify_texture(path)
        if role == "extra":
            by_role["extra"].append(path)
            continue
        if by_role[role] is None:
            by_role[role] = path

    return by_role


def import_obj(obj_path):
    before = set(bpy.data.objects)
    if hasattr(bpy.ops.wm, "obj_import"):
        bpy.ops.wm.obj_import(filepath=str(obj_path))
    else:
        bpy.ops.import_scene.obj(filepath=str(obj_path))

    imported = [obj for obj in bpy.data.objects if obj not in before]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"No mesh object imported from {obj_path}")
    return meshes


def image_node(nodes, path, role, location):
    node = nodes.new(type="ShaderNodeTexImage")
    node.name = f"{role}_{path.name}"
    node.label = f"{role}: {path.name}"
    node.location = location
    node.image = bpy.data.images.load(str(path), check_existing=True)
    if role == "diffuse":
        node.image.colorspace_settings.name = "sRGB"
    else:
        node.image.colorspace_settings.name = "Non-Color"
    return node


def set_principled_input(node, names, value):
    for name in names:
        if name in node.inputs:
            node.inputs[name].default_value = value
            return True
    return False


def build_material(textures, normal_strength=1.0, bump_strength=0.06):
    material = bpy.data.materials.new("CLO_All_Textures")
    material.use_nodes = True
    material.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    if hasattr(material, "cycles"):
        material.cycles.displacement_method = "BOTH"

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new(type="ShaderNodeOutputMaterial")
    output.location = (620, 0)
    principled = nodes.new(type="ShaderNodeBsdfPrincipled")
    principled.location = (300, 0)
    set_principled_input(principled, ["Roughness"], 0.55)
    set_principled_input(principled, ["Metallic"], 0.0)
    if "Alpha" in principled.inputs:
        principled.inputs["Alpha"].default_value = 1.0
    links.new(principled.outputs["BSDF"], output.inputs["Surface"])

    loaded = {}
    diffuse = textures.get("diffuse")
    if diffuse:
        tex = image_node(nodes, diffuse, "diffuse", (-620, 220))
        loaded["diffuse"] = str(diffuse)
        links.new(tex.outputs["Color"], principled.inputs["Base Color"])

    roughness = textures.get("roughness")
    if roughness and "Roughness" in principled.inputs:
        tex = image_node(nodes, roughness, "roughness", (-620, -30))
        loaded["roughness"] = str(roughness)
        links.new(tex.outputs["Color"], principled.inputs["Roughness"])

    metallic = textures.get("metallic")
    if metallic and "Metallic" in principled.inputs:
        tex = image_node(nodes, metallic, "metallic", (-620, -250))
        loaded["metallic"] = str(metallic)
        links.new(tex.outputs["Color"], principled.inputs["Metallic"])

    alpha = textures.get("alpha")
    if alpha and "Alpha" in principled.inputs:
        tex = image_node(nodes, alpha, "alpha", (-620, -470))
        loaded["alpha"] = str(alpha)
        links.new(tex.outputs["Color"], principled.inputs["Alpha"])
        material.blend_method = "BLEND"
        material.use_screen_refraction = True

    normal_output = None
    normal = textures.get("normal")
    if normal:
        tex = image_node(nodes, normal, "normal", (-220, -250))
        normal_map = nodes.new(type="ShaderNodeNormalMap")
        normal_map.name = "Normal_Map"
        normal_map.location = (40, -250)
        normal_map.inputs["Strength"].default_value = normal_strength
        links.new(tex.outputs["Color"], normal_map.inputs["Color"])
        normal_output = normal_map.outputs["Normal"]
        loaded["normal"] = str(normal)

    displacement = textures.get("displacement")
    if displacement:
        tex = image_node(nodes, displacement, "displacement", (-220, -520))
        bump = nodes.new(type="ShaderNodeBump")
        bump.name = "Displacement_As_Bump"
        bump.location = (40, -520)
        bump.inputs["Strength"].default_value = bump_strength
        bump.inputs["Distance"].default_value = 0.08
        links.new(tex.outputs["Color"], bump.inputs["Height"])
        if normal_output:
            links.new(normal_output, bump.inputs["Normal"])
        normal_output = bump.outputs["Normal"]
        loaded["displacement"] = str(displacement)

        displacement_node = nodes.new(type="ShaderNodeDisplacement")
        displacement_node.name = "Material_Displacement"
        displacement_node.location = (300, -520)
        displacement_node.inputs["Scale"].default_value = 0.015
        links.new(tex.outputs["Color"], displacement_node.inputs["Height"])
        links.new(displacement_node.outputs["Displacement"], output.inputs["Displacement"])

    if normal_output and "Normal" in principled.inputs:
        links.new(normal_output, principled.inputs["Normal"])

    for index, extra in enumerate(textures.get("extra", [])):
        tex = image_node(nodes, extra, "extra", (-940, -120 * index))
        loaded.setdefault("extra", []).append(str(extra))

    return material, loaded


def assign_material(meshes, material):
    for obj in meshes:
        obj.data.materials.clear()
        obj.data.materials.append(material)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        try:
            bpy.ops.object.shade_smooth()
        except Exception:
            pass
        obj.select_set(False)


def purge_unused_materials_and_images():
    for material in list(bpy.data.materials):
        if material.users == 0:
            bpy.data.materials.remove(material)
    for image in list(bpy.data.images):
        if image.users == 0:
            bpy.data.images.remove(image)


def bounds(meshes):
    points = []
    for obj in meshes:
        for corner in obj.bound_box:
            points.append(obj.matrix_world @ Vector(corner))
    min_v = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    max_v = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    center = (min_v + max_v) * 0.5
    size = max(max_v.x - min_v.x, max_v.y - min_v.y, max_v.z - min_v.z)
    return min_v, max_v, center, max(size, 0.001)


def look_at(obj, target):
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_camera_and_lighting(meshes):
    _, _, center, size = bounds(meshes)

    key_data = bpy.data.lights.new("Temp_Key_Area", type="AREA")
    key_data.energy = 700.0
    key_data.size = size * 1.8
    key = bpy.data.objects.new("Temp_Key_Area", key_data)
    bpy.context.collection.objects.link(key)
    key.location = center + Vector((size * 1.3, -size * 1.6, size * 1.8))
    look_at(key, center)

    fill_data = bpy.data.lights.new("Temp_Fill_Area", type="AREA")
    fill_data.energy = 140.0
    fill_data.size = size * 2.5
    fill = bpy.data.objects.new("Temp_Fill_Area", fill_data)
    bpy.context.collection.objects.link(fill)
    fill.location = center + Vector((-size * 1.8, size * 1.2, size * 1.2))
    look_at(fill, center)

    camera_data = bpy.data.cameras.new("Texture_Check_Camera")
    camera = bpy.data.objects.new("Texture_Check_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = center + Vector((0.0, -size * 2.6, size * 0.55))
    look_at(camera, center)
    camera_data.lens = 55.0
    camera_data.sensor_width = 36.0
    bpy.context.scene.camera = camera

    return camera


def configure_render(render_path, resolution, samples):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.film_transparent = False
    scene.world = scene.world or bpy.data.worlds.new("World")
    scene.world.color = (0.78, 0.78, 0.78)
    scene.render.filepath = str(render_path)
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def write_report(report_path, report):
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    args = parse_args()
    input_dir = ensure_path(args.input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    obj_path = discover_obj(input_dir, args.obj)
    mtl_path = obj_path.with_suffix(".mtl")
    render_path = ensure_path(args.render_path) if args.render_path else input_dir / "texture_mapping_preview.png"
    blend_path = ensure_path(args.blend_path) if args.blend_path else input_dir / "texture_mapping.blend"
    report_path = input_dir / "texture_mapping_report.json"

    clear_scene()

    texture_paths = discover_texture_files(input_dir)
    mtl_refs = parse_mtl_texture_refs(mtl_path, input_dir)
    textures = pick_textures(texture_paths, mtl_refs)
    meshes = import_obj(obj_path)
    material, loaded = build_material(textures, args.normal_strength, args.bump_strength)
    assign_material(meshes, material)
    purge_unused_materials_and_images()
    setup_camera_and_lighting(meshes)
    configure_render(render_path, args.resolution, args.cycles_samples)

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    bpy.ops.render.render(write_still=True)

    report = {
        "input_dir": str(input_dir),
        "obj_path": str(obj_path),
        "mtl_path": str(mtl_path) if mtl_path.exists() else "",
        "texture_files": [str(path) for path in texture_paths],
        "mtl_refs": {key: str(value) for key, value in mtl_refs.items()},
        "selected_textures": {
            key: ([str(item) for item in value] if isinstance(value, list) else (str(value) if value else ""))
            for key, value in textures.items()
        },
        "loaded_textures": loaded,
        "mesh_objects": [obj.name for obj in meshes],
        "material": material.name,
        "render_path": str(render_path),
        "blend_path": str(blend_path),
        "all_texture_files_loaded": sorted(
            str(image.filepath_from_user())
            for image in bpy.data.images
            if image.filepath_from_user()
        ),
    }
    write_report(report_path, report)

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
