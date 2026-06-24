# Dataset Creation Instruction

## Confirmed Current Pipeline

현재 스크립트와 `dataset_config.json` 기준 stage는 4개다.

| Stage | Script | Output |
| --- | --- | --- |
| `1` | `scripts/01_clo_make_dataset.py` | `dataset/01_draped_garments/` |
| `2` | `scripts/02_generate_proxy.py` | `dataset/02_body_proxy_gt/` |
| `3` | `scripts/03_blender_render.py` | `dataset/03_blender_multiview/` |
| `4` | `scripts/04_gs_train.py` | `dataset/04_3dgs/` |

`scripts/run_stages.py`는 `pipeline.run_stages`에 적힌 stage만 순서대로 실행한다.
현재 config는 `[3, 4]`로 Blender render와 3DGS training만 실행한다.

## Dataset Target Spec

- 옷 카테고리 5개: 반팔 티셔츠, 긴팔 티셔츠, 원피스, 치마, 바지
- Garment geometry 10개: geometry가 서로 다른 옷
- Fabric 30개: 물성이 서로 다른 `.zfab` fabric dataset
- Avatar 8개: normal, over weight, under weight 계열의 female/male body
  - `f_34`, `f_38`, `f_42`, `f_46`
  - `m_44`, `m_48`, `m_52`, `m_56`

## Confirmed Local Inputs

현재 workspace에서 확인된 입력은 아래와 같다.

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
      base0.material.json
      ...
      base4.material.json
```

확인된 사실: 현재 local fabric은 5개다. 목표 스펙의 30개 fabric은 아직 현재 입력 폴더에는 없다.

확인된 사실: 현재 local garment/avatar `.zprj`는 8개다. 목표 스펙의 옷 카테고리 5개와 garment geometry 10개를 구분하는 별도 metadata는 현재 config에 없다.

## Core Rules

- Fabric bending sampler는 legacy로 보존하지만 기본 pipeline에서는 실행하지 않는다.
- Stage 1은 `dataset/input/fabrics/*.zfab` 원본 fabric과 `dataset/input/garments/**/*.zprj`를 조합한다.
- Output relative sample path는 `{fabric_id}/{garment_id}`다.
- 예: `base0/f_34`
- Stage 1, 3, 4는 같은 relative sample path를 공유한다.
- Stage 2 body proxy는 body/avatar ID별로 한 번 생성한다.

## Output Structure

```text
dataset/
  01_draped_garments/
    base0/
      f_34/
        obj.obj
        obj.mtl
        summary.json
      ...
    dataset_summary.json
  02_body_proxy_gt/
    f_34/
      avatar.obj
      avatar_meta.json
      proxy/
        body_proxy_gt.json
        body_proxy_tensor.npy
        slices_png/
    ...
  03_blender_multiview/
    base0/
      f_34/
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
    base0/
      f_34/
        cameras.json
        point_cloud/
        point_cloud.ply
    pipeline_summary.json
```

## Config Requirements

핵심 값:

| Key | Current Value / Meaning |
| --- | --- |
| `project.output_dir` | `dataset` |
| `inputs.garments_dir` | `input/garments` |
| `inputs.fabrics_dir` | `input/fabrics` |
| `naming.draped_dir` | `01_draped_garments` |
| `naming.body_proxy_dir` | `02_body_proxy_gt` |
| `naming.render_dir` | `03_blender_multiview` |
| `naming.gs_dir` | `04_3dgs` |
| `naming.sample_dir_template` | `{fabric_id}/{garment_id}` |
| `pipeline.run_stages` | 실행할 stage 목록 |
| `blender_render.num_views` | `48` |
| `blender_render.resolution` | `512` |

## Stage Execution

```bash
python scripts/run_stages.py --config dataset_config.json
```

`pipeline.run_stages` 예시:

| Value | Meaning |
| --- | --- |
| `[1]` | CLO drape + OBJ export |
| `[2]` | body proxy GT 생성 |
| `[3]` | Blender multi-view render |
| `[4]` | 3DGS training |
| `[3, 4]` | 기존 drape 결과로 render 후 3DGS 실행 |
| `[1, 2, 3, 4]` | 전체 pipeline 실행 |

주의: stage 1과 stage 2는 CLO Python API가 필요하므로 CLO Python 환경에서 실행해야 한다.

## Stage Details

Stage 1 input:

- `dataset/input/garments/**/*.zprj`
- `dataset/input/fabrics/*.zfab`

Stage 1 output:

- `dataset/01_draped_garments/<fabric_id>/<garment_id>/obj.obj`
- `dataset/01_draped_garments/<fabric_id>/<garment_id>/obj.mtl`
- `dataset/01_draped_garments/<fabric_id>/<garment_id>/summary.json`
- `dataset/01_draped_garments/dataset_summary.json`

Stage 2 output:

- `dataset/02_body_proxy_gt/<body_id>/avatar.obj`
- `dataset/02_body_proxy_gt/<body_id>/avatar_meta.json`
- `dataset/02_body_proxy_gt/<body_id>/proxy/body_proxy_gt.json`
- `dataset/02_body_proxy_gt/<body_id>/proxy/body_proxy_tensor.npy`
- `dataset/02_body_proxy_gt/<body_id>/proxy/slices_png/`

Stage 3 output:

- `dataset/03_blender_multiview/<fabric_id>/<garment_id>/images/*.png`
- `dataset/03_blender_multiview/<fabric_id>/<garment_id>/camera_parameters.json`
- `dataset/03_blender_multiview/<fabric_id>/<garment_id>/mesh_vertices.csv`
- `dataset/03_blender_multiview/<fabric_id>/<garment_id>/sparse/0/cameras.txt`
- `dataset/03_blender_multiview/<fabric_id>/<garment_id>/sparse/0/images.txt`
- `dataset/03_blender_multiview/<fabric_id>/<garment_id>/sparse/0/points3D.txt`
- `dataset/03_blender_multiview/<fabric_id>/<garment_id>/sparse/0/points3D.ply`

Stage 4 output:

- `dataset/04_3dgs/<fabric_id>/<garment_id>/point_cloud/iteration_*/point_cloud.ply`
- `dataset/04_3dgs/<fabric_id>/<garment_id>/point_cloud.ply`
- optional render output under `dataset/04_3dgs/<fabric_id>/<garment_id>/train/`
- `dataset/04_3dgs/pipeline_summary.json`

## Quality Checks

- 각 fabric/avatar 조합마다 OBJ, MTL, texture files가 존재해야 한다.
- Blender render는 sample당 48 views를 생성해야 한다.
- `sparse/0/cameras.txt`와 `sparse/0/images.txt`가 있어야 3DGS stage 대상이 된다.
- `dataset_summary.json`과 실제 folder path가 일치해야 한다.
- 3DGS 실행 환경에는 `diff_gaussian_rasterization`, `simple_knn`, `fused_ssim` CUDA extension이 설치되어 있어야 한다.

## Deprecated Bending Notes

이전 bending 실험용 코드와 config는 보존한다.

- `scripts/01_clo_fab_sampler.py`
- `fabric_sampler.sample_count`
- `fabric_sampler.sample_bins`
- `naming.fabric_dir`
- `naming.fabric_variant_dir_template`
- `naming.bend_dir_template`

현재 dataset 생성에서는 위 값들이 기본 sample 수나 output path를 결정하지 않는다.
