# CLO Dataset Instructions 
각 단계를 순서대로 따로 실행하고, 모든 경로는 하나의 config에서 관리한다.

기본적으로 3번 단계 빼고는 각 단계의 코드를 순서대로 실행하면 코드 이해 없이 코드 복사/붙여넣기로 실행 가능하다.

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
  01_fabric_bending/
    base_000.zfab
    base_000.material.json
    ...
    summary_bending_sampling.json
  02_draped_garments/
    000_base_000/
      draped_garment.zprj
      summary.json
    ...
    dataset_summary.json
  03_manual_obj_exports/
    000_base_000/
      obj.obj
      obj.mtl
      obj_diffuse*.png
      obj_normal*.png
  04_blender_multiview/
    000_base_000/
      images/
      sparse/0/
        cameras.txt
        images.txt
        points3D.txt
        points3D.ply
      camera_parameters.json
      mesh_vertices.csv
      dataset_summary.json
  05_3dgs/
    000_base_000/
```

Sample folder naming:

`{index:03d}_{fabric_stem}`

Example:

`base_000.zfab` -> `000_base_000`

## 1. Fabric Bending 샘플 만들기

Script:

`PATH/scripts/clo_fab_sampler.py`

Config sections:

- `inputs.base_fabric_zfab`
- `project.output_dir`
- `naming.fabric_dir`
- `naming.fabric_file_template`
- `fabric_sampler`

Input:

- 원본 원단: `inputs.base_fabric_zfab`

Output:

- `output_dir/01_fabric_bending/base_000.zfab`
- `output_dir/01_fabric_bending/base_001.zfab`
- `output_dir/01_fabric_bending/*.material.json`
- `output_dir/01_fabric_bending/summary_bending_sampling.json`


## 2. CLO Simulation 후 Draped ZPRJ 저장

Script:

`PATH/scripts/clo_make_dataset.py`

Config sections:

- `inputs.base_garment_zprj`
- `project.output_dir`
- `naming.fabric_dir`
- `naming.draped_dir`
- `clo_simulation`

Input:

- 원단들: `output_dir/01_fabric_bending/base_*.zfab`
- base model: `inputs.base_garment_zprj`

Output:

- `output_dir/02_draped_garments/<sample>/draped_garment.zprj`
- `output_dir/02_draped_garments/<sample>/summary.json`
- `output_dir/02_draped_garments/dataset_summary.json`
- `output_dir/03_manual_obj_exports/<sample>/`
- `output_dir/05_3dgs/<sample>/`


Important:

- 이 단계에서는 OBJ export를 하지 않는다.
- `clo_simulation.export_obj`는 `false`로 둔다.
- CLO Python Script Editor 안에서 실행한다.

## 3. Draped ZPRJ에서 OBJ 수동 Export

Script:

없음. CLO UI에서 수동으로 export한다.

Input:

- `output_dir/02_draped_garments/<sample>/draped_garment.zprj`

Output:

- `output_dir/03_manual_obj_exports/<sample>/obj.obj`
- `output_dir/03_manual_obj_exports/<sample>/obj.mtl`
- `output_dir/03_manual_obj_exports/<sample>/obj_diffuse.png` 또는 `obj_diffuse_1001.png`
- `output_dir/03_manual_obj_exports/<sample>/obj_normal.png` 또는 `obj_normal_1001.png`

Manual rule:

- `<sample>` 폴더 이름은 2단계 sample 폴더와 동일하게 맞춘다.
- 예: `000_base_000`
- Export 하기 전에 UV map에서 각 pattern을 겹치지 않게하고 0~1 범위 내로 옮겨야한다.
- Export 팝업 창에서 scale은 1%로 바꿔야한다(이후 blender에서 import 할 때의 scale을 고려).

## 4. Blender Multi-view Rendering

Script:

`PATH/scripts/blender_render.py`

Config sections:

- `project.output_dir`
- `naming.manual_obj_dir`
- `naming.render_dir`
- `blender_render.render_all_samples`
- `blender_render.sample_index`
- `blender_render`

Input:

`blender_render.render_all_samples`로 렌더 범위를 고른다.

- `true`: `output_dir/03_manual_obj_exports/*/obj.obj`가 있는 모든 sample을 렌더링한다.
- `false`: `blender_render.sample_index` 하나만 렌더링한다.

예를 들어 `render_all_samples = true`이면 자동으로 아래 구조를 전부 읽는다.

- `output_dir/03_manual_obj_exports/<sample>/obj.obj`
- `output_dir/03_manual_obj_exports/<sample>/obj_diffuse*.png`
- `output_dir/03_manual_obj_exports/<sample>/obj_normal*.png`


Output:

- `output_dir/04_blender_multiview/<sample>/images/*.png`
- `output_dir/04_blender_multiview/<sample>/camera_parameters.json`
- `output_dir/04_blender_multiview/<sample>/sparse/0/cameras.txt`
- `output_dir/04_blender_multiview/<sample>/sparse/0/images.txt`
- `output_dir/04_blender_multiview/<sample>/sparse/0/points3D.txt`
- `output_dir/04_blender_multiview/<sample>/sparse/0/points3D.ply`
- `output_dir/04_blender_multiview/<sample>/mesh_vertices.csv`
- `output_dir/04_blender_multiview/<sample>/dataset_summary.json`
- `output_dir/04_blender_multiview/pipeline_summary.json`


sample 하나만 렌더링하려면 `blender_render.render_all_samples`를 `false`로 바꾸고 `blender_render.sample_index`를 지정한다.

## 5. 3DGS 학습

아직 실행하지 않는다.

Current config:

- `3dgs_training.enabled`: `false`

나중에 사용할 input:

- 4단계 multi-view images
- COLMAP camera files
- geometry `.ply`

나중에 만들 output:

- `output_dir/05_3dgs/garment_3dgs.ply`
