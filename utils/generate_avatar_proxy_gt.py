#!/usr/bin/env python3
import argparse
import json
import math
import os
from collections import defaultdict, deque

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def parse_obj(path):
    vertices = []
    faces = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                _, x, y, z, *rest = line.strip().split()
                vertices.append([float(x), float(y), float(z)])
            elif line.startswith("f "):
                raw = line.strip().split()[1:]
                idx = []
                for item in raw:
                    # Supports v, v/vt, v//vn, v/vt/vn.
                    vi = int(item.split("/")[0])
                    idx.append(vi - 1 if vi > 0 else len(vertices) + vi)
                if len(idx) >= 3:
                    for i in range(1, len(idx) - 1):
                        faces.append([idx[0], idx[i], idx[i + 1]])
    return np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.int64)


def unique_points(points, tol):
    uniq = []
    keys = set()
    for p in points:
        key = (round(float(p[0]) / tol), round(float(p[1]) / tol))
        if key not in keys:
            keys.add(key)
            uniq.append(p)
    return uniq


def intersect_triangle_y(tri, y, eps=1e-9):
    pts = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        a = tri[i]
        b = tri[j]
        da = a[1] - y
        db = b[1] - y

        if abs(da) < eps and abs(db) < eps:
            # Coplanar triangle edge. Ignored to avoid over-drawing flat bands.
            continue
        if abs(da) < eps:
            pts.append(np.array([a[0], a[2]], dtype=np.float64))
        if abs(db) < eps:
            pts.append(np.array([b[0], b[2]], dtype=np.float64))
        if da * db < 0.0:
            t = (y - a[1]) / (b[1] - a[1])
            p = a + t * (b - a)
            pts.append(np.array([p[0], p[2]], dtype=np.float64))

    pts = unique_points(pts, tol=1e-7)
    if len(pts) == 2 and np.linalg.norm(pts[0] - pts[1]) > eps:
        return pts[0], pts[1]
    return None


def slice_segments(vertices, faces, y):
    segments = []
    for face in faces:
        tri = vertices[face]
        ymin = tri[:, 1].min()
        ymax = tri[:, 1].max()
        if y < ymin or y > ymax:
            continue
        seg = intersect_triangle_y(tri, y)
        if seg is not None:
            segments.append(seg)
    return segments


def convex_hull(points):
    pts = sorted(set((float(p[0]), float(p[1])) for p in points))
    if len(pts) <= 1:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def polygon_area(poly):
    if len(poly) < 3:
        return 0.0
    area = 0.0
    for i in range(len(poly)):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % len(poly)]
        area += x1 * z2 - x2 * z1
    return abs(area) * 0.5


def cluster_segments(segments, snap_tol):
    if not segments:
        return []

    node_pos = {}
    graph = defaultdict(set)

    def key_of(p):
        return (round(float(p[0]) / snap_tol), round(float(p[1]) / snap_tol))

    for a, b in segments:
        ka = key_of(a)
        kb = key_of(b)
        node_pos.setdefault(ka, np.asarray(a, dtype=np.float64))
        node_pos.setdefault(kb, np.asarray(b, dtype=np.float64))
        graph[ka].add(kb)
        graph[kb].add(ka)

    components = []
    visited = set()
    for start in graph:
        if start in visited:
            continue
        q = deque([start])
        visited.add(start)
        keys = []
        while q:
            cur = q.popleft()
            keys.append(cur)
            for nxt in graph[cur]:
                if nxt not in visited:
                    visited.add(nxt)
                    q.append(nxt)

        pts = np.asarray([node_pos[k] for k in keys], dtype=np.float64)
        center = pts.mean(axis=0)
        min_x, min_z = pts.min(axis=0)
        max_x, max_z = pts.max(axis=0)
        hull = convex_hull(pts)
        area = polygon_area(hull)
        perimeter = 0.0
        key_set = set(keys)
        seen_edges = set()
        for k in keys:
            for n in graph[k]:
                if n in key_set:
                    edge = tuple(sorted([k, n]))
                    if edge not in seen_edges:
                        seen_edges.add(edge)
                        perimeter += float(np.linalg.norm(node_pos[k] - node_pos[n]))

        components.append(
            {
                "center_x": float(center[0]),
                "center_z": float(center[1]),
                "left_radius": float(center[0] - min_x),
                "right_radius": float(max_x - center[0]),
                "back_radius": float(center[1] - min_z),
                "front_radius": float(max_z - center[1]),
                "bbox_width_x": float(max_x - min_x),
                "bbox_depth_z": float(max_z - min_z),
                "area_convex_hull": float(area),
                "perimeter_segments": float(perimeter),
                "num_points": int(len(pts)),
                "valid": True,
            }
        )

    components.sort(key=lambda c: (-c["area_convex_hull"], c["center_x"]))
    return components


def pad_components(components, top_k):
    empty = {
        "center_x": 0.0,
        "center_z": 0.0,
        "left_radius": 0.0,
        "right_radius": 0.0,
        "back_radius": 0.0,
        "front_radius": 0.0,
        "bbox_width_x": 0.0,
        "bbox_depth_z": 0.0,
        "area_convex_hull": 0.0,
        "perimeter_segments": 0.0,
        "num_points": 0,
        "valid": False,
    }
    out = components[:top_k]
    while len(out) < top_k:
        out.append(dict(empty))
    return out


def draw_slice_png(path, segments, components, y_norm, y_abs, xlim, zlim, size=768):
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    margin = 56
    w = size - 2 * margin
    h = size - 2 * margin
    xmin, xmax = xlim
    zmin, zmax = zlim
    sx = w / max(xmax - xmin, 1e-9)
    sz = h / max(zmax - zmin, 1e-9)
    s = min(sx, sz)
    xmid = 0.5 * (xmin + xmax)
    zmid = 0.5 * (zmin + zmax)

    def to_px(p):
        x, z = float(p[0]), float(p[1])
        px = size / 2 + (x - xmid) * s
        py = size / 2 - (z - zmid) * s
        return (px, py)

    # Axes.
    draw.line([(margin, size / 2), (size - margin, size / 2)], fill=(225, 225, 225), width=1)
    draw.line([(size / 2, margin), (size / 2, size - margin)], fill=(225, 225, 225), width=1)
    draw.text((16, 12), f"y_norm={y_norm:.3f}, y={y_abs:.4f}", fill=(0, 0, 0))
    draw.text((16, 32), f"components={len(components)}", fill=(0, 0, 0))

    for a, b in segments:
        draw.line([to_px(a), to_px(b)], fill=(30, 30, 30), width=2)

    colors = [
        (220, 50, 47),
        (38, 139, 210),
        (133, 153, 0),
        (211, 54, 130),
        (181, 137, 0),
        (108, 113, 196),
    ]
    for i, c in enumerate(components):
        color = colors[i % len(colors)]
        cx, cz = c["center_x"], c["center_z"]
        xmin_c = cx - c["left_radius"]
        xmax_c = cx + c["right_radius"]
        zmin_c = cz - c["back_radius"]
        zmax_c = cz + c["front_radius"]
        p1 = to_px((xmin_c, zmin_c))
        p2 = to_px((xmax_c, zmax_c))
        rect = [
            min(p1[0], p2[0]),
            min(p1[1], p2[1]),
            max(p1[0], p2[0]),
            max(p1[1], p2[1]),
        ]
        draw.rectangle(rect, outline=color, width=2)
        pc = to_px((cx, cz))
        r = 4
        draw.ellipse([pc[0] - r, pc[1] - r, pc[0] + r, pc[1] + r], fill=color)
        draw.text((pc[0] + 6, pc[1] + 4), str(i), fill=color)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)


def generate_body_proxy_gt(
    obj_path,
    out_dir,
    num_slices=10,
    top_k=4,
    slice_min=0.08,
    slice_max=0.88,
    png_size=768,
    json_file_name="body_proxy_gt.json",
    tensor_file_name="body_proxy_tensor.npy",
    png_dir_name="slices_png",
):
    if num_slices <= 0:
        raise RuntimeError("--num_slices must be positive.")
    if not (0.0 <= slice_min < slice_max <= 1.0):
        raise RuntimeError("--slice_min and --slice_max must satisfy 0 <= min < max <= 1.")

    out_dir = os.path.abspath(out_dir)
    obj_path = os.path.abspath(obj_path)
    os.makedirs(out_dir, exist_ok=True)
    png_dir = os.path.join(out_dir, png_dir_name)
    os.makedirs(png_dir, exist_ok=True)

    vertices, faces = parse_obj(obj_path)
    if len(vertices) == 0 or len(faces) == 0:
        raise RuntimeError("OBJ must contain vertices and faces.")

    bbox_min = vertices.min(axis=0)
    bbox_max = vertices.max(axis=0)
    height = float(bbox_max[1] - bbox_min[1])
    if height <= 0:
        raise RuntimeError("Invalid avatar height.")

    x_margin = 0.05 * max(float(bbox_max[0] - bbox_min[0]), 1e-6)
    z_margin = 0.05 * max(float(bbox_max[2] - bbox_min[2]), 1e-6)
    xlim = (float(bbox_min[0] - x_margin), float(bbox_max[0] + x_margin))
    zlim = (float(bbox_min[2] - z_margin), float(bbox_max[2] + z_margin))

    max_range = float(max(bbox_max - bbox_min))
    snap_tol = max_range * 1e-5

    y_norm_values = np.linspace(slice_min, slice_max, num_slices)
    slices = []
    tensor_rows = []
    tensor_feature_names = [
        "valid",
        "y_norm",
        "center_x_over_height",
        "center_z_over_height",
        "left_radius_over_height",
        "right_radius_over_height",
        "back_radius_over_height",
        "front_radius_over_height",
        "bbox_width_x_over_height",
        "bbox_depth_z_over_height",
        "area_convex_hull_over_height2",
        "perimeter_segments_over_height",
    ]
    for si, y_norm in enumerate(y_norm_values):
        y_abs = float(bbox_min[1] + y_norm * height)
        segments = slice_segments(vertices, faces, y_abs)
        components = cluster_segments(segments, snap_tol=snap_tol)
        padded = pad_components(components, top_k)
        tensor_slice = []
        for c in padded:
            tensor_slice.append(
                [
                    1.0 if c["valid"] else 0.0,
                    float(y_norm),
                    c["center_x"] / height,
                    c["center_z"] / height,
                    c["left_radius"] / height,
                    c["right_radius"] / height,
                    c["back_radius"] / height,
                    c["front_radius"] / height,
                    c["bbox_width_x"] / height,
                    c["bbox_depth_z"] / height,
                    c["area_convex_hull"] / (height * height),
                    c["perimeter_segments"] / height,
                ]
            )
        tensor_rows.append(tensor_slice)

        png_name = f"slice_{si:03d}_ynorm_{y_norm:.3f}.png"
        png_path = os.path.join(png_dir, png_name)
        draw_slice_png(
            png_path,
            segments,
            components,
            float(y_norm),
            y_abs,
            xlim,
            zlim,
            size=png_size,
        )

        slices.append(
            {
                "slice_index": si,
                "y_norm": float(y_norm),
                "y_abs": y_abs,
                "num_segments": int(len(segments)),
                "num_components_raw": int(len(components)),
                "components_top_k": padded,
                "png": os.path.relpath(png_path, out_dir),
            }
        )

    gt = {
        "source_obj": obj_path,
        "representation": "part-free multi-component vertical support profile",
        "coordinate_convention": {
            "height_axis": "y",
            "slice_plane": "x-z",
            "front_radius": "+z from component center",
            "back_radius": "-z from component center",
            "right_radius": "+x from component center",
            "left_radius": "-x from component center",
        },
        "metadata": {
            "num_vertices": int(len(vertices)),
            "num_triangles": int(len(faces)),
            "num_slices": int(num_slices),
            "slice_min": float(slice_min),
            "slice_max": float(slice_max),
            "slice_policy": "uniform y-normalized slices; feet and head are skipped by default",
            "top_k_components": int(top_k),
            "tensor_shape": [int(num_slices), int(top_k), len(tensor_feature_names)],
            "tensor_feature_names": tensor_feature_names,
            "height_abs": height,
            "bbox_min": bbox_min.tolist(),
            "bbox_max": bbox_max.tolist(),
            "snap_tol": snap_tol,
        },
        "slices": slices,
    }

    json_path = os.path.join(out_dir, json_file_name)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(gt, f, indent=2)

    tensor_path = os.path.join(out_dir, tensor_file_name)
    np.save(tensor_path, np.asarray(tensor_rows, dtype=np.float32))

    print(f"[OK] wrote {json_path}")
    print(f"[OK] wrote {tensor_path}")
    print(f"[OK] wrote {len(slices)} slice PNGs to {png_dir}")
    return {
        "json_path": json_path,
        "tensor_path": tensor_path,
        "png_dir": png_dir,
        "num_slices": int(num_slices),
        "top_k": int(top_k),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate multi-component vertical support proxy GT from an avatar OBJ."
    )
    parser.add_argument("--obj", required=True, help="Path to avatar OBJ.")
    parser.add_argument("--out_dir", required=True, help="Output directory.")
    parser.add_argument("--num_slices", type=int, default=10, help="Number of y-normalized slices.")
    parser.add_argument("--top_k", type=int, default=4, help="Max components per slice.")
    parser.add_argument(
        "--slice_min",
        type=float,
        default=0.08,
        help="Lowest normalized y slice. Skips feet by default.",
    )
    parser.add_argument(
        "--slice_max",
        type=float,
        default=0.88,
        help="Highest normalized y slice. Skips head/top boundary by default.",
    )
    parser.add_argument("--png_size", type=int, default=768)
    parser.add_argument("--json_name", default="body_proxy_gt.json")
    parser.add_argument("--tensor_name", default="body_proxy_tensor.npy")
    parser.add_argument("--png_dir_name", default="slices_png")
    args = parser.parse_args()
    generate_body_proxy_gt(
        args.obj,
        args.out_dir,
        num_slices=args.num_slices,
        top_k=args.top_k,
        slice_min=args.slice_min,
        slice_max=args.slice_max,
        png_size=args.png_size,
        json_file_name=args.json_name,
        tensor_file_name=args.tensor_name,
        png_dir_name=args.png_dir_name,
    )


if __name__ == "__main__":
    main()
