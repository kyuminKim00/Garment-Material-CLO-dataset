# Dataset Creation Instruction

## Goal

같은 garment geometry와 같은 원본 fabric을 여러 body variant에 drape해서, body shape 차이에 따른 draped garment geometry와 multi-view render dataset을 만든다.

이전 규칙에서는 fabric bending 값을 바꾼 variant를 만든 뒤 각 garment/body에 적용했다. 현재 규칙에서는 fabric bending을 바꾸지 않는다. `input/fabrics/*.zfab`의 원본 fabric을 그대로 각 body variant에 적용한다.

## Body Variants

현재 body input은 male/female만이 아니라 weight category까지 포함한다.

| ID | Meaning |
| --- | --- |
| `f_unw` | female underweight |
| `f_nrw` | female normal weight |
| `f_ovw` | female overweight |
| `m_unw` | male underweight |
| `m_nrw` | male normal weight |
| `m_ovw` | male overweight |

현재 데이터셋 루트는 `D:/KKM/CLO-dataset`이며, 입력은 다음 구조를 따른다.

```text
D:/KKM/CLO-dataset/
  input/
    garments/
      f_nrw.zprj
      f_ovw.zprj
      f_unw.zprj
      m_nrw.zprj
      m_ovw.zprj
      m_unw.zprj
    fabrics/
      base0.zfab
      base1.zfab
      base2.zfab
      base3.zfab
      base4.zfab
```

## Core Rules

- Fabric bending은 변경하지 않는다.
- `scripts/01_clo_fab_sampler.py`는 삭제하지 않지만, 현재 pipeline에서는 실행하지 않는다.
- 각 sample은 `input/fabrics/<fabric_id>.zfab` 원본 fabric과 `input/garments/<garment_id>.zprj` body/garment project의 조합이다.
- CLO drape, OBJ export, Blender multi-view rendering 로직은 기존과 동일하게 유지한다.
- Output relative path는 `{fabric_id}/{garment_id}`이다. 예: `base0/f_nrw`.

## Output Structure

```text
output_dir/
  dataset_config.json
  input/
    garments/
    fabrics/
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
          0000.png
          ...
          0047.png
        camera_parameters.json
        mesh_vertices.csv
        dataset_summary.json
        sparse/0/
          cameras.txt
          images.txt
          points3D.txt
          points3D.ply
    pipeline_summary.json
  03_3dgs/
    base0/
      f_nrw/
```

`01_draped_garments`, `02_blender_multiview`, `03_3dgs`는 같은 relative sample path를 공유한다.

## Config Requirements

`dataset_config.json`의 핵심 값:

| Key | Value / Meaning |
| --- | --- |
| `project.output_dir` | `D:/KKM/CLO-dataset` |
| `inputs.garments_dir` | `input/garments` |
| `inputs.fabrics_dir` | `input/fabrics` |
| `naming.draped_dir` | `01_draped_garments` |
| `naming.render_dir` | `02_blender_multiview` |
| `naming.gs_dir` | `03_3dgs` |
| `naming.sample_dir_template` | `{fabric_id}/{garment_id}` |
| `clo_simulation.export_obj` | `true` |
| `clo_simulation.skip_render` | `true` |
| `blender_render.num_views` | `48` |
| `blender_render.resolution` | `512` |

`fabric_sampler` section은 legacy compatibility를 위해 남겨 둔다. 현재 기본 pipeline에서는 사용하지 않는다.

## Stage Execution

실행할 단계 목록은 `pipeline.run_stages`로 관리한다.

| Value | Stage |
| --- | --- |
| `1` | CLO drape + OBJ/MTL/texture export |
| `2` | Blender multi-view rendering |
| `3` | 3DGS training |

Examples:

| `pipeline.run_stages` | Meaning |
| --- | --- |
| `[1]` | CLO drape만 실행 |
| `[2]` | Blender render만 실행 |
| `[2, 3]` | Blender render 후 3DGS 실행 |
| `[1, 2, 3]` | 전체 pipeline 실행 |

Run:

```powershell
python C:\Users\CGnA\Desktop\CLO\scripts\run_stages.py --config C:\Users\CGnA\Desktop\CLO\dataset_config.json
```

CLO stage는 CLO Python Script Editor 안에서 실행해야 한다.

## Stage 1: Draped Garments

Input:

- `output_dir/input/garments/**/*.zprj`
- `output_dir/input/fabrics/*.zfab`

Output:

- `output_dir/01_draped_garments/<fabric_id>/<garment_id>/obj.obj`
- `output_dir/01_draped_garments/<fabric_id>/<garment_id>/obj.mtl`
- `output_dir/01_draped_garments/<fabric_id>/<garment_id>/<CLO-exported texture files>`
- `output_dir/01_draped_garments/<fabric_id>/<garment_id>/summary.json`
- `output_dir/01_draped_garments/dataset_summary.json`

`clo_simulation.save_sim_zprj = true`이면 `draped_garment.zprj`도 저장한다.

## Stage 2: Blender Multi-View

Input:

- `output_dir/01_draped_garments/**/obj.obj`
- 같은 sample folder 안의 `obj.mtl`과 CLO-exported texture files

Output:

- `output_dir/02_blender_multiview/<fabric_id>/<garment_id>/images/*.png`
- `output_dir/02_blender_multiview/<fabric_id>/<garment_id>/camera_parameters.json`
- `output_dir/02_blender_multiview/<fabric_id>/<garment_id>/mesh_vertices.csv`
- `output_dir/02_blender_multiview/<fabric_id>/<garment_id>/sparse/0/cameras.txt`
- `output_dir/02_blender_multiview/<fabric_id>/<garment_id>/sparse/0/images.txt`
- `output_dir/02_blender_multiview/<fabric_id>/<garment_id>/sparse/0/points3D.txt`
- `output_dir/02_blender_multiview/<fabric_id>/<garment_id>/sparse/0/points3D.ply`

## Quality Checks

- 각 fabric/body 조합마다 OBJ, MTL, texture files가 존재해야 한다.
- 같은 fabric 안에서 body variant별 drape 결과가 같은 relative layout으로 정렬되어야 한다.
- Fabric texture는 body variant가 달라도 동일해야 한다.
- Transparent or semi-transparent fabric은 사용하지 않는다.
- Blender render는 sample당 48 views를 생성해야 한다.
- `dataset_summary.json`과 실제 folder path가 일치해야 한다.

## Deprecated Bending Notes

이전 bending 실험용 코드와 config는 보존한다.

- `scripts/01_clo_fab_sampler.py`
- `fabric_sampler.sample_count`
- `fabric_sampler.sample_bins`
- `naming.fabric_dir`
- `naming.fabric_variant_dir_template`
- `naming.bend_dir_template`

현재 dataset 생성에서는 위 값들이 sample 수나 output path를 결정하지 않는다.
