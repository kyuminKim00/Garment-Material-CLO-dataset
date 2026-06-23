# CLO Dataset Pipeline

이 파이프라인은 `project.output_dir` 아래의 원본 garment/body `.zprj`와 fabric `.zfab`을 조합해 draped garment OBJ bundle을 만들고, 그 결과를 Blender multi-view 데이터셋으로 렌더링한다.

## Current Dataset Root

기본 config는 아래 데이터셋을 사용한다.

```text
D:/KKM/CLO-dataset/
  input/
    fabrics/
      base0.zfab
      base1.zfab
      base2.zfab
      base3.zfab
      base4.zfab
    garments/
      f_nrw.zprj
      f_ovw.zprj
      f_unw.zprj
      m_nrw.zprj
      m_ovw.zprj
      m_unw.zprj
```

`f/m`은 female/male, `unw/nrw/ovw`는 underweight/normal weight/overweight body variant를 뜻한다.

## Output Tree

샘플 폴더는 fabric 먼저, body variant 다음 순서로 만든다.

```text
output_dir/
  01_draped_garments/
    base0/
      f_nrw/
        obj.obj
        obj.mtl
        <CLO-exported texture files>
        summary.json
      f_ovw/
      f_unw/
      m_nrw/
      m_ovw/
      m_unw/
    dataset_summary.json
  02_blender_multiview/
    base0/
      f_nrw/
        images/
        sparse/0/
          cameras.txt
          images.txt
          points3D.txt
          points3D.ply
        camera_parameters.json
        mesh_vertices.csv
        dataset_summary.json
    pipeline_summary.json
  03_3dgs/
    base0/
      f_nrw/
```

Relative sample path:

```text
{fabric_id}/{garment_id}
```

Example:

```text
input/fabrics/base0.zfab + input/garments/f_nrw.zprj
-> 01_draped_garments/base0/f_nrw/
-> 02_blender_multiview/base0/f_nrw/
-> 03_3dgs/base0/f_nrw/
```

## Config

Main config:

```text
C:\Users\CGnA\Desktop\CLO\dataset_config.json
```

Important fields:

- `project.output_dir`: dataset root, currently `D:/KKM/CLO-dataset`
- `inputs.garments_dir`: source `.zprj` pool, currently `input/garments`
- `inputs.fabrics_dir`: source `.zfab` pool, currently `input/fabrics`
- `naming.draped_dir`: `01_draped_garments`
- `naming.render_dir`: `02_blender_multiview`
- `naming.gs_dir`: `03_3dgs`
- `naming.sample_dir_template`: `{fabric_id}/{garment_id}`
- `pipeline.run_stages`: exact stages to run, for example `[1]` or `[2, 3]`

Stage numbers:

- `1`: CLO drape + OBJ export
- `2`: Blender multi-view rendering
- `3`: 3DGS training

Examples:

- `[1]`: CLO drape만 실행
- `[2, 3]`: 기존 `01_draped_garments` 결과를 사용해 Blender render 후 3DGS 실행
- `[1, 2, 3]`: 전체 pipeline 실행

## 1. CLO Drape And OBJ Export

Run inside CLO Python Script Editor:

```powershell
python C:\Users\CGnA\Desktop\CLO\scripts\run_stages.py --config C:\Users\CGnA\Desktop\CLO\dataset_config.json
```

`pipeline.run_stages = [1]`이면 이 단계만 실행한다.

Input:

- `output_dir/input/garments/**/*.zprj`
- `output_dir/input/fabrics/*.zfab`

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
- draped `.zprj` 저장 여부는 `clo_simulation.save_sim_zprj`에서 고른다.
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

## 4. 00-04 단계 선택 실행

Script:

`PATH/scripts/run_stages.py`

이 스크립트는 CLO를 새로 실행하지 않는다. CLO Python Script Editor에 코드를 붙여넣어 실행하는 용도다.
실행할 마지막 단계는 config의 `pipeline.run_until_stage`에서 관리한다.

```powershell
python PATH/scripts/run_stages.py
```

- `0`: config 경로만 확인하고 종료
- `1`: stage 01 실행
- `2`: stage 01-02 실행
- `3`: stage 01-03 실행
- `4`: stage 01-04 실행

Config 경로는 스크립트 안에 기본값으로 하드코딩되어 있다.

```python
CONFIG_JSON_PATH = r"C:\Users\CGnA\Desktop\CLO\dataset_config.json"
```

Blender가 `PATH`에 없으면 `--blender`로 Blender 실행 파일 경로를 넘긴다.
기본 Blender/Python 실행 파일은 `pipeline.blender_executable`, `pipeline.python_executable`에서 관리한다.

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
output_dir/01_draped_garments/**/obj.obj
```

and writes the same relative layout under:

```text
output_dir/02_blender_multiview/
```

Rendering logic, camera sampling, texture loading, COLMAP-style output generation은 기존과 동일하다.

## 3. 3DGS Training

`pipeline.run_stages`에 `3`을 포함하면 `02_blender_multiview`의 sample들을 읽어 같은 relative layout으로 `03_3dgs`에 학습 결과를 쓴다.

## Deprecated: Fabric Bending Sampler

`scripts/01_clo_fab_sampler.py`와 `fabric_sampler` config section은 삭제하지 않고 보존한다. 다만 현재 dataset 규칙에서는 bending을 바꾼 `.zfab`을 만들지 않으며, drape stage는 `input/fabrics/*.zfab` 원본 파일을 그대로 사용한다.
