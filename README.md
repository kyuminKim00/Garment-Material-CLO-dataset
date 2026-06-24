# CLO Dataset Pipeline

이 README는 코드 실행 방법과 stage별 입출력 구조만 설명한다. 데이터셋 목표 스펙은 `instruction.md`를 본다.

## Run

`scripts/run_stages.py`는 `dataset_config.json`의 `pipeline.run_stages`에 적힌 stage만 순서대로 실행한다.

```bash
python scripts/run_stages.py --config dataset_config.json
```

Blender/Python 실행 파일을 임시로 바꾸려면:

```bash
python scripts/run_stages.py --config dataset_config.json --blender /path/to/blender --python /path/to/python
```

## Stages

| Stage | Script | 역할 |
| --- | --- | --- |
| `1` | `scripts/01_clo_make_dataset.py` | CLO drape + OBJ/MTL export |
| `2` | `scripts/02_generate_proxy.py` | avatar body proxy GT 생성 |
| `3` | `scripts/03_blender_render.py` | Blender multi-view + COLMAP-style files 생성 |
| `4` | `scripts/04_gs_train.py` | Gaussian Splatting 학습 |

`pipeline.run_stages` 예:

| 값 | 실행 |
| --- | --- |
| `[1]` | Stage 1만 |
| `[2]` | Stage 2만 |
| `[3]` | Stage 3만 |
| `[4]` | Stage 4만 |
| `[3, 4]` | render 후 3DGS |
| `[1, 2, 3, 4]` | 전체 pipeline |

주의: Stage 1과 Stage 2는 CLO Python API가 필요하므로 CLO Python 환경에서 실행해야 한다.

## Input Structure

`project.output_dir`가 dataset root다. `inputs.garments_dir`, `inputs.fabrics_dir`가 상대 경로이면 `project.output_dir` 기준으로 해석된다.

```text
<project.output_dir>/
  input/
    garments/
      <garment_or_avatar_id>.zprj
      ...
    fabrics/
      <fabric_id>.zfab
      ...
      material_json/
        <fabric_id>.material.json
```

관련 config:

| Config | 의미 |
| --- | --- |
| `project.output_dir` | dataset root |
| `inputs.garments_dir` | `.zprj` 입력 위치 |
| `inputs.fabrics_dir` | `.zfab` 입력 위치 |

## Output Structure

기본 sample path는 `naming.sample_dir_template`으로 정한다.

```text
{fabric_id}/{garment_id}
```

예:

```text
input/fabrics/base0.zfab + input/garments/f_34.zprj
-> 01_draped_garments/base0/f_34/
-> 03_blender_multiview/base0/f_34/
-> 04_3dgs/base0/f_34/
```

전체 output 구조:

```text
<project.output_dir>/
  01_draped_garments/
    <fabric_id>/<garment_id>/
      obj.obj
      obj.mtl
      summary.json
    dataset_summary.json

  02_body_proxy_gt/
    <body_id>/
      avatar.obj
      avatar_meta.json
      proxy/
        body_proxy_gt.json
        body_proxy_tensor.npy
        slices_png/

  03_blender_multiview/
    <fabric_id>/<garment_id>/
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
    <fabric_id>/<garment_id>/
      cameras.json
      point_cloud/
        iteration_*/point_cloud.ply
      point_cloud.ply
      train/
    pipeline_summary.json
```

관련 config:

| Config | 의미 |
| --- | --- |
| `naming.sample_dir_template` | sample별 상대 경로 형식 |
| `naming.draped_dir` | Stage 1 output folder |
| `naming.body_proxy_dir` | Stage 2 output folder |
| `naming.render_dir` | Stage 3 output folder |
| `naming.gs_dir` | Stage 4 output folder |
| `naming.obj_file` | OBJ 파일명 |
| `naming.mtl_file` | MTL 파일명 |
| `naming.sample_summary_file` | sample summary 파일명 |

## Stage 1: CLO Drape

Input:

- `<project.output_dir>/<inputs.garments_dir>/**/*.zprj`
- `<project.output_dir>/<inputs.fabrics_dir>/*.zfab`

Output:

- `<project.output_dir>/<naming.draped_dir>/<fabric_id>/<garment_id>/obj.obj`
- `<project.output_dir>/<naming.draped_dir>/<fabric_id>/<garment_id>/obj.mtl`
- `<project.output_dir>/<naming.draped_dir>/<fabric_id>/<garment_id>/summary.json`
- `<project.output_dir>/<naming.draped_dir>/dataset_summary.json`

주요 config:

| Config | 의미 |
| --- | --- |
| `clo_simulation.sim_steps` | CLO simulation step 수 |
| `clo_simulation.max_samples` | 처리 sample 수 제한. `0`이면 전체 |
| `clo_simulation.save_sim_zprj` | draped `.zprj` 저장 여부 |
| `clo_simulation.export_obj` | OBJ/MTL export 여부 |
| `clo_simulation.stop_on_first_failure` | 첫 실패에서 중단할지 여부 |

## Stage 2: Body Proxy GT

Input:

- `<project.output_dir>/<naming.draped_dir>/dataset_summary.json`
- 각 body/avatar의 source `.zprj`

Output:

- `<project.output_dir>/<body_proxy_gt.output_dir>/<body_id>/avatar.obj`
- `<project.output_dir>/<body_proxy_gt.output_dir>/<body_id>/avatar_meta.json`
- `<project.output_dir>/<body_proxy_gt.output_dir>/<body_id>/proxy/body_proxy_gt.json`
- `<project.output_dir>/<body_proxy_gt.output_dir>/<body_id>/proxy/body_proxy_tensor.npy`
- `<project.output_dir>/<body_proxy_gt.output_dir>/<body_id>/proxy/slices_png/`

주요 config:

| Config | 의미 |
| --- | --- |
| `body_proxy_gt.enabled` | stage 내부 실행 여부 |
| `body_proxy_gt.output_dir` | output folder |
| `body_proxy_gt.body_dir_template` | body별 folder 이름 |
| `body_proxy_gt.export_scale` | avatar OBJ scale |
| `body_proxy_gt.num_slices` | proxy slice 수 |
| `body_proxy_gt.top_k` | slice당 component 수 |
| `body_proxy_gt.slice_min`, `slice_max` | proxy 생성 height 범위 |
| `body_proxy_gt.reuse_existing` | 기존 결과 재사용 여부 |

## Stage 3: Blender Multi-View

Input:

- `<project.output_dir>/<naming.draped_dir>/**/obj.obj`
- 같은 folder의 `obj.mtl`과 texture files

Output:

- `<project.output_dir>/<naming.render_dir>/<fabric_id>/<garment_id>/images/*.png`
- `<project.output_dir>/<naming.render_dir>/<fabric_id>/<garment_id>/camera_parameters.json`
- `<project.output_dir>/<naming.render_dir>/<fabric_id>/<garment_id>/mesh_vertices.csv`
- `<project.output_dir>/<naming.render_dir>/<fabric_id>/<garment_id>/sparse/0/cameras.txt`
- `<project.output_dir>/<naming.render_dir>/<fabric_id>/<garment_id>/sparse/0/images.txt`
- `<project.output_dir>/<naming.render_dir>/<fabric_id>/<garment_id>/sparse/0/points3D.txt`
- `<project.output_dir>/<naming.render_dir>/<fabric_id>/<garment_id>/sparse/0/points3D.ply`

주요 config:

| Config | 의미 |
| --- | --- |
| `blender_render.render_all_samples` | 전체 sample render 여부 |
| `blender_render.sample_index` | 단일 sample render index |
| `blender_render.num_views` | view 수 |
| `blender_render.resolution` | render 해상도 |
| `blender_render.camera_radius` | camera radius. `0` 이하면 자동 |
| `blender_render.radius_scale` | 자동 radius 배율 |
| `blender_render.lens_mm` | camera focal length |
| `blender_render.samples` | Cycles sample 수 |
| `blender_render.hdri_path` | HDRI 경로 |

## Stage 4: 3DGS Training

Input:

- `<project.output_dir>/<naming.render_dir>/<fabric_id>/<garment_id>/images/`
- `<project.output_dir>/<naming.render_dir>/<fabric_id>/<garment_id>/sparse/0/cameras.txt`
- `<project.output_dir>/<naming.render_dir>/<fabric_id>/<garment_id>/sparse/0/images.txt`

Output:

- `<project.output_dir>/<naming.gs_dir>/<fabric_id>/<garment_id>/point_cloud/iteration_*/point_cloud.ply`
- `<project.output_dir>/<naming.gs_dir>/<fabric_id>/<garment_id>/point_cloud.ply`
- `<project.output_dir>/<naming.gs_dir>/pipeline_summary.json`

주요 config:

| Config | 의미 |
| --- | --- |
| `3dgs_training.gaussian_splatting_dir` | Gaussian Splatting repo 경로 |
| `3dgs_training.python_executable` | `train.py` 실행 Python |
| `3dgs_training.extra_args` | `train.py` 추가 인자 |
| `3dgs_training.skip_existing` | 기존 `point_cloud.ply`가 있으면 skip |
| `3dgs_training.render_after_train` | 학습 후 preview render 실행 |
| `3dgs_training.render_extra_args` | `render.py` 추가 인자 |

3DGS 환경에는 아래 CUDA extension이 설치되어 있어야 한다.

- `diff_gaussian_rasterization`
- `simple_knn`
- `fused_ssim`
