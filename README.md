# CLO Dataset Instructions 
각 단계를 순서대로 따로 실행하고, 모든 경로는 하나의 config에서 관리한다.

각 단계의 코드를 순서대로 실행하면 코드 이해 없이 코드 복사/붙여넣기로 실행 가능하다.

Dataset 생성 instruction은 instruction.md 에 명시

Config:

`PATH/dataset_pipeline_config.json`

Config에서 직접 바꾸는 핵심 값은 세 개다.

- `project.output_dir`: 전체 데이터셋 출력 루트
- `inputs.base_fabric_zfab`: 원본 원단 `base.zfab`
- `inputs.base_garment_zprj`: garment + avatar base model `.zprj`

나머지 output은 `project.output_dir` 아래에서 `naming` 규칙으로 자동 생성된다.

## Output Tree

기본 구조:

```text
output_dir/
  input/
    garments/
      base.zprj
      other_garment.zprj
    fabrics/
      fabric_a.zfab
      fabric_b.zfab
  01_fabric_bending/
    fabric_a/
      bend_000/
        fabric.zfab
        material.json
      bend_001/
        fabric.zfab
        material.json
    summary_bending_sampling.json
  02_draped_garments/
    base/
      fabric_a/
        bend_000/
          draped_garment.zprj
          obj.obj
          obj.mtl
          <CLO-exported texture files>
          material.json
          summary.json
    dataset_summary.json
  03_blender_multiview/
    base/
      fabric_a/
        bend_000/
          images/
          sparse/0/
            cameras.txt
            images.txt
            points3D.txt
            points3D.ply
          camera_parameters.json
          mesh_vertices.csv
          dataset_summary.json
  04_3dgs/
    base/
      fabric_a/
        bend_000/
```

Sample folder naming:

`{garment_id}/{fabric_id}/{bend_id}`

Example:

`input/garments/base.zprj` + `input/fabrics/fabric_a.zfab` + `bend_000`
-> `base/fabric_a/bend_000`

## 1. Fabric Bending 샘플 만들기

Script:

`PATH/scripts/clo_fab_sampler.py`

Config sections:

- `inputs.input_dir`
- `inputs.fabrics_dir`
- `project.output_dir`
- `naming.fabric_dir`
- `naming.fabric_variant_dir_template`
- `naming.fabric_file_template`
- `fabric_sampler`

Input:

- 원본 원단: `inputs.base_fabric_zfab`

Output:

- `output_dir/01_fabric_bending/<fabric_id>/<bend_id>/fabric.zfab`
- `output_dir/01_fabric_bending/<fabric_id>/<bend_id>/material.json`
- `output_dir/01_fabric_bending/summary_bending_sampling.json`


## 2. CLO Simulation 후 Draped ZPRJ 및 OBJ 저장

Script:

`PATH/scripts/clo_make_dataset.py`

Config sections:

- `inputs.input_dir`
- `inputs.garments_dir`
- `project.output_dir`
- `naming.fabric_dir`
- `naming.draped_dir`
- `naming.sample_dir_template`
- `clo_simulation`

Input:

- 원단들: `output_dir/01_fabric_bending/base_*.zfab`
- garments: `output_dir/input/garments/**/*.zprj`

Output:

- `output_dir/02_draped_garments/<garment_id>/<fabric_id>/<bend_id>/draped_garment.zprj`
- `output_dir/02_draped_garments/<garment_id>/<fabric_id>/<bend_id>/obj.obj`
- `output_dir/02_draped_garments/<garment_id>/<fabric_id>/<bend_id>/obj.mtl`
- `output_dir/02_draped_garments/<garment_id>/<fabric_id>/<bend_id>/<CLO-exported texture files>`
- `output_dir/02_draped_garments/<garment_id>/<fabric_id>/<bend_id>/summary.json`
- `output_dir/02_draped_garments/dataset_summary.json`
- `output_dir/04_3dgs/<garment_id>/<fabric_id>/<bend_id>/`


Important:

- 이 단계에서 OBJ/MTL/texture를 자동 export한다.
- `clo_simulation.export_obj`는 `true`로 둔다.
- CLO Python Script Editor 안에서 실행한다.

## 3. Blender Multi-view Rendering

Script:

`PATH/scripts/blender_render.py`

Config sections:

- `project.output_dir`
- `naming.render_dir`
- `blender_render.render_all_samples`
- `blender_render.sample_index`
- `blender_render`

Input:

`blender_render.render_all_samples`로 렌더 범위를 고른다.

- `true`: `output_dir/02_draped_garments/*/obj.obj`가 있는 모든 sample을 렌더링한다.
- `false`: `blender_render.sample_index` 하나만 렌더링한다.

예를 들어 `render_all_samples = true`이면 자동으로 아래 구조를 전부 읽는다.

- `output_dir/02_draped_garments/<sample>/obj.obj`
- `output_dir/02_draped_garments/<sample>/obj.mtl`
- `output_dir/02_draped_garments/<sample>/<CLO-exported texture files>`

Output:

- `output_dir/03_blender_multiview/<sample>/images/*.png`
- `output_dir/03_blender_multiview/<sample>/camera_parameters.json`
- `output_dir/03_blender_multiview/<sample>/sparse/0/cameras.txt`
- `output_dir/03_blender_multiview/<sample>/sparse/0/images.txt`
- `output_dir/03_blender_multiview/<sample>/sparse/0/points3D.txt`
- `output_dir/03_blender_multiview/<sample>/sparse/0/points3D.ply`
- `output_dir/03_blender_multiview/<sample>/mesh_vertices.csv`
- `output_dir/03_blender_multiview/<sample>/dataset_summary.json`
- `output_dir/03_blender_multiview/pipeline_summary.json`


sample 하나만 렌더링하려면 `blender_render.render_all_samples`를 `false`로 바꾸고 `blender_render.sample_index`를 지정한다.

## 4. 01-03 한번에 실행

Script:

`PATH/scripts/run_stages_01_03.py`

이 스크립트는 CLO를 새로 실행하지 않는다. CLO Python Script Editor에 코드를 붙여넣어 실행하면 아래 순서로 진행한다.

1. 현재 CLO Python 프로세스에서 `clo_fab_sampler.py` 실행
2. 현재 CLO Python 프로세스에서 `clo_make_dataset.py` 실행
3. Blender를 background mode로 실행해서 `blender_render.py` 실행

Config 경로는 스크립트 안에 기본값으로 하드코딩되어 있다.

```python
CONFIG_JSON_PATH = r"C:\Users\CGnA\Desktop\CLO\dataset_config.json"
```

Blender가 `PATH`에 없으면 `--blender`로 Blender 실행 파일 경로를 넘긴다.

## 5. 3DGS 학습

아직 실행하지 않는다.

Current config:

- `3dgs_training.enabled`: `false`

나중에 사용할 input:

- 3단계 multi-view images
- COLMAP camera files
- geometry `.ply`

나중에 만들 output:

- `output_dir/04_3dgs/garment_3dgs.ply`

## Current Multi-Body Layout

Place body-specific base garments under `output_dir/input/garments`:

```text
input/
  garments/
    female/
      base.zprj
    male/
      base.zprj
  fabrics/
    base0.zfab
    base1.zfab
```

The pipeline discovers all `.zprj` and `.zfab` files automatically.
`clo_make_dataset.py` writes samples as:

```text
02_draped_garments/
  female/<fabric_id>/<bend_id>/
  male/<fabric_id>/<bend_id>/
```

The same relative layout is used for `02_draped_garments`, `03_blender_multiview`, and `04_3dgs`.

Set `fabric_sampler.sample_count` to choose how many bending variants are generated per fabric.
For `ui_bucket_jittered`, `sample_bins[*].count` acts as the relative bucket weight, while `sample_count` controls the final total count including the 0 and 100 anchors.
