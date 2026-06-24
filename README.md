# CLO Dataset Pipeline

이 repo는 CLO garment/avatar project와 `.zfab` fabric을 조합해 draped OBJ, body proxy GT, Blender multi-view render, 3DGS 결과를 생성한다.

## Current State

확인된 현재 config:

- Dataset root: `dataset`
- Stage list: `pipeline.run_stages = [3, 4]`
- Render output: `dataset/03_blender_multiview`
- 3DGS output: `dataset/04_3dgs`

현재 local input:

- Avatar/garment `.zprj` 8개: `f_34`, `f_38`, `f_42`, `f_46`, `m_44`, `m_48`, `m_52`, `m_56`
- Fabric `.zfab` 5개: `base0` ... `base4`

목표 dataset spec:

- 옷 카테고리 5개: 반팔 티셔츠, 긴팔 티셔츠, 원피스, 치마, 바지
- Garment geometry 10개: geometry가 서로 다른 옷
- Fabric 30개: 물성이 서로 다른 데이터셋
- Avatar 8개: normal, over weight, under weight 계열의 female/male body

Unknown:

- 현재 config에는 옷 카테고리 5개와 garment geometry 10개를 나타내는 metadata/schema가 아직 없다.
- 현재 local fabric은 5개라 목표 30개와 다르다.

## Pipeline Stages

| Stage | Script | Output |
| --- | --- | --- |
| `1` | `scripts/01_clo_make_dataset.py` | `dataset/01_draped_garments` |
| `2` | `scripts/02_generate_proxy.py` | `dataset/02_body_proxy_gt` |
| `3` | `scripts/03_blender_render.py` | `dataset/03_blender_multiview` |
| `4` | `scripts/04_gs_train.py` | `dataset/04_3dgs` |

Run selected stages:

```bash
python scripts/run_stages.py --config dataset_config.json
```

`pipeline.run_stages` examples:

- `[1]`: CLO drape + OBJ export
- `[2]`: body proxy GT
- `[3]`: Blender multi-view render
- `[4]`: 3DGS training
- `[3, 4]`: render 후 3DGS
- `[1, 2, 3, 4]`: 전체 pipeline

Stage 1과 stage 2는 CLO Python API가 필요하다.

## Input Layout

```text
dataset/input/
  garments/
    f_34.zprj
    f_38.zprj
    f_42.zprj
    f_46.zprj
    m_44.zprj
    m_48.zprj
    m_52.zprj
    m_56.zprj
  fabrics/
    base0.zfab
    base1.zfab
    base2.zfab
    base3.zfab
    base4.zfab
    material_json/
```

Relative sample path:

```text
{fabric_id}/{garment_id}
```

Example:

```text
dataset/input/fabrics/base0.zfab + dataset/input/garments/f_34.zprj
-> dataset/01_draped_garments/base0/f_34/
-> dataset/03_blender_multiview/base0/f_34/
-> dataset/04_3dgs/base0/f_34/
```

## Output Layout

```text
dataset/
  01_draped_garments/
    base0/f_34/
      obj.obj
      obj.mtl
      summary.json
    dataset_summary.json
  02_body_proxy_gt/
    f_34/
      avatar.obj
      avatar_meta.json
      proxy/
        body_proxy_gt.json
        body_proxy_tensor.npy
        slices_png/
  03_blender_multiview/
    base0/f_34/
      images/
      camera_parameters.json
      mesh_vertices.csv
      sparse/0/
        cameras.txt
        images.txt
        points3D.txt
        points3D.ply
    pipeline_summary.json
  04_3dgs/
    base0/f_34/
      cameras.json
      point_cloud/
      point_cloud.ply
    pipeline_summary.json
```

## Important Config

```json
{
  "project": {
    "output_dir": "dataset"
  },
  "pipeline": {
    "run_stages": [3, 4],
    "blender_executable": "blender",
    "python_executable": "python"
  },
  "naming": {
    "draped_dir": "01_draped_garments",
    "body_proxy_dir": "02_body_proxy_gt",
    "render_dir": "03_blender_multiview",
    "gs_dir": "04_3dgs",
    "sample_dir_template": "{fabric_id}/{garment_id}"
  }
}
```

## 3DGS Environment Note

Stage 4 calls `/home/cgna/km/gaussian-splatting/train.py`.

The active Python environment must have these Gaussian Splatting CUDA extensions installed:

- `diff_gaussian_rasterization`
- `simple_knn`
- `fused_ssim`

If `ModuleNotFoundError: No module named 'diff_gaussian_rasterization'` occurs, install the submodules into the same Python env used by `3dgs_training.python_executable`.

## Deprecated

`scripts/01_clo_fab_sampler.py` and `fabric_sampler` config are kept for legacy bending experiments. The current default pipeline uses original `.zfab` files from `dataset/input/fabrics`.
