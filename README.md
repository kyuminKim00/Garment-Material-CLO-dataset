# CLO Dataset Pipeline

이 파이프라인은 `project.output_dir` 아래의 원본 garment/body `.zprj`와 fabric `.zfab`을 조합해 draped garment OBJ bundle을 만들고, 그 결과를 Blender multi-view 데이터셋으로 렌더링한다.

현재 규칙에서는 fabric bending variant를 생성하지 않는다. `scripts/01_clo_fab_sampler.py`는 이전 실험 재현용으로 남겨 두지만, 기본 실행 경로에서는 사용하지 않는다.

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

- `output_dir/01_draped_garments/<fabric_id>/<garment_id>/obj.obj`
- `output_dir/01_draped_garments/<fabric_id>/<garment_id>/obj.mtl`
- `output_dir/01_draped_garments/<fabric_id>/<garment_id>/<CLO-exported texture files>`
- `output_dir/01_draped_garments/<fabric_id>/<garment_id>/summary.json`
- `output_dir/01_draped_garments/dataset_summary.json`

`clo_simulation.save_sim_zprj`가 `true`이면 같은 sample folder에 `draped_garment.zprj`도 저장한다.

## 2. Blender Multi-View Rendering

`pipeline.run_stages`에 `2`를 포함하면 실행된다. 예를 들어 `[2]`는 render만, `[2, 3]`은 render 후 3DGS를 실행한다.

The renderer scans:

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
