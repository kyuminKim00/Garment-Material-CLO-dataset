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
- Garment geometry 50개: 5개 카테고리별 10개씩, geometry가 서로 다른 옷
- Fabric 30개: 물성이 서로 다른 `.zfab` fabric dataset
- Avatar 8개: normal, over weight, under weight 계열의 female/male body
  - `f_34`, `f_38`, `f_42`, `f_46`
  - `m_44`, `m_48`, `m_52`, `m_56`

## Total Dataset Count


| Item | Count | Calculation | Note |
| --- | ---: | --- | --- |
| 옷 카테고리 | 5 | fixed | 반팔 티셔츠, 긴팔 티셔츠, 원피스, 치마, 바지 |
| Garment geometry | 50 | `5 categories x 10 geometries` | 카테고리별 10개씩, 서로 다른 의류 geometry |
| Fabric | 30 | fixed | 서로 다른 물성의 `.zfab` |
| Avatar | 8 | fixed | `f_34`, `f_38`, `f_42`, `f_46`, `m_44`, `m_48`, `m_52`, `m_56` |
| Body proxy GT | 8 | `8 avatars` | avatar별 `body_proxy_gt.json`, `body_proxy_tensor.npy` 1개 |
| Draped garment sample | 12,000 | `5 x 10 x 30 x 8` | 각 category/garment/fabric/avatar 조합 |
| Draped OBJ file | 12,000 | `5 x 10 x 30 x 8` | `01_draped_garments/**/obj.obj` |
| Multi-view image | 576,000 | `12,000 x 48 views` | `03_blender_multiview/**/images/*.png` |
| 3DGS PLY | 12,000 | `5 x 10 x 30 x 8` | sample당 최종 `point_cloud.ply` 1개 |

3DGS 학습과 최종 3DGS PLY 생성은 연세대에서 수행한다.
Body proxy GT는 avatar별로 한 번 생성하고, 각 garment/fabric/avatar sample에서 같은 avatar proxy를 참조한다.

## Dataset Selection Notes

Garment 선택 규칙:

- 5개 카테고리에서 골고루 선택한다: 반팔 티셔츠, 긴팔 티셔츠, 원피스, 치마, 바지.
- 각 카테고리 안에서는 서로 다른 geometry를 가진 옷을 선택한다.
- 단, 너무 특이한 옷은 제외한다.
- 제외 예: 비정상적으로 긴 장식, 과도하게 복잡한 레이어, 시뮬레이션이 쉽게 깨질 수 있는 구조, 일반적인 착장 분포에서 벗어나는 극단적 실루엣.
- 목표는 카테고리별 다양성은 확보하되, dataset 전체가 일반적인 의류 분포를 대표하도록 유지하는 것이다.

Fabric 선택 규칙:

- 총 30개 fabric은 물성 분포가 최대한 균일해야 한다.
- 빳빳한 fabric, 중간 정도의 fabric, 흐물거리는 fabric이 한쪽으로 치우치지 않도록 고른다.
- bending, stretch, shear 등 drape에 영향을 주는 물성이 서로 다른 sample을 포함한다.
- 같은 느낌의 fabric이 과도하게 반복되면 제외하거나 다른 물성으로 교체한다.
- fabric은 절대 투명하거나 반투명하면 안 된다.
- render에서 안쪽 body/avatar가 비치는 fabric은 사용하지 않는다.

Avatar 선택 규칙:

- avatar는 체형별로 나누어 사용한다.
- 사용할 avatar 8개는 별도로 제공되는 것을 그대로 사용한다.
- 대상 avatar ID는 `f_34`, `f_38`, `f_42`, `f_46`, `m_44`, `m_48`, `m_52`, `m_56`이다.
- avatar는 normal, over weight, under weight 계열이 포함되도록 구성한다.
- dataset 생성 시 garment/fabric 조합은 같은 avatar set에 대해 일관되게 적용한다.

## Core Rules

- Stage 1은 `dataset/input/fabrics/*.zfab` 원본 fabric과 `dataset/input/garments/**/*.zprj`를 조합한다.
- Output relative sample path는 `{fabric_id}/{garment_id}`다.
- 예: `base0/f_34`
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

## Quality Checks

- 각 fabric/avatar 조합마다 OBJ, MTL, texture files가 존재해야 한다.
- 투명하거나 반투명해서 내부가 비치는 fabric은 없어야 한다.
- Blender render는 sample당 48 views를 생성해야 한다.
- `sparse/0/cameras.txt`와 `sparse/0/images.txt`가 있어야 3DGS 학습이 가능하다.
