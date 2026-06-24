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
- Fabric 30개: fabric pool 50개 중 물성 분포가 균일하도록 30개 선택
- Avatar base 2개:
  - female: `FV2.1_Luna_Teenager`
  - male: `MV2.1_Jinho`
- Avatar body variant 8개: female/male 각각 `CLO_EU_Female`, `CLO_EU_Male` size에서 4단계씩 sampling

## Total Dataset Count

Fabric, avatar size, pose는 sampling 규칙에 따라 배정한다.

| Item | Count | Calculation | Note |
| --- | ---: | --- | --- |
| 옷 카테고리 | 5 | fixed | 반팔 티셔츠, 긴팔 티셔츠, 원피스, 치마, 바지 |
| Garment geometry | 50 | `5 categories x 10 geometries` | 카테고리별 10개씩, 서로 다른 의류 geometry |
| Fabric pool | 50 | fixed | 후보 `.zfab` pool |
| Selected fabric | 30 | sample from 50 | 물성 분포가 균일하도록 선택 |
| Avatar base | 2 | fixed | `FV2.1_Luna_Teenager`, `MV2.1_Jinho` |
| Avatar body variant | 8 | `2 avatar bases x 4 size levels` | female/male 각각 4단계 size |
| Body proxy GT | 8 | `8 body variants` | body variant별 `body_proxy_gt.json`, `body_proxy_tensor.npy` 1개 |
| Draped garment sample | 12,000 | `5 x 10 x 30 x 8` | sampled garment/fabric/body/pose 조합 |
| Draped OBJ, texture file | 12,000 | `5 x 10 x 30 x 8` | `01_draped_garments/**/obj.obj, .png` |
| Multi-view image | 576,000 | `12,000 x 48 views` | `03_blender_multiview/**/images/*.png` |
| 3DGS PLY | 12,000 | `5 x 10 x 30 x 8` | sample당 최종 `point_cloud.ply` 1개 |

3DGS 학습과 최종 3DGS PLY 생성은 연세대에서 수행한다.
Body proxy GT는 body variant별로 한 번 생성하고, 각 garment/fabric/body/pose sample에서 같은 body variant proxy를 참조한다.

## Dataset Selection Notes

Garment 선택 규칙:

- 5개 카테고리에서 골고루 선택한다: 반팔 티셔츠, 긴팔 티셔츠, 원피스, 치마, 바지.
- 각 카테고리 안에서는 서로 다른 geometry를 가진 옷을 선택한다.
- 단, 너무 특이한 옷은 제외한다.
- 제외 예: 비정상적으로 긴 장식, 과도하게 복잡한 레이어, 시뮬레이션이 쉽게 깨질 수 있는 구조, 일반적인 착장 분포에서 벗어나는 극단적 실루엣.
- 목표는 카테고리별 다양성은 확보하되, dataset 전체가 일반적인 의류 분포를 대표하도록 유지하는 것이다.

Fabric 선택 규칙:

- 후보 fabric 50개 중 30개를 선택한다.
- 선택된 30개 fabric은 물성 분포가 최대한 균일해야 한다.
- 빳빳한 fabric, 중간 정도의 fabric, 흐물거리는 fabric이 한쪽으로 치우치지 않도록 고른다.
- bending, stretch, shear 등 drape에 영향을 주는 물성이 서로 다른 sample을 포함한다.
- 같은 느낌의 fabric이 과도하게 반복되면 제외하거나 다른 물성으로 교체한다.
- fabric은 절대 투명하거나 반투명하면 안 된다.
- render에서 안쪽 body/avatar가 비치는 fabric은 사용하지 않는다.
- 본 연구는 fabric의 물성 중 strecth, shear, bending, density의 각 방향은 신경쓰지 않고 하나의 값을 추론한다.
- ex) bending weft/warp/bias 값이 다를 수 있지만 모델은 하나의 값을 출력함
- 이를 학습시키기 위해 각 fabric의 물성을 확인하고 각 방향의 값이 다르면 하나의 값으로 조정해주는 작업이 필요하다.
- ex) bending parameter가 각 방향으로 (30/40/30) 이라고하면 전부 30으로 맞춰야한다.

Avatar 선택 규칙:

- base avatar는 female `FV2.1_Luna_Teenager`, male `MV2.1_Jinho`를 사용한다.
- size는 `CLO_EU_Female`, `CLO_EU_Male` size table에서 성별별 4단계를 random sampling한다.
- 4단계 size는 under weight부터 over weight까지 체형 변화가 모두 보이도록 고른다.
- 결과적으로 female 4개, male 4개, 총 8개 body variant를 사용한다.
- avatar size sampling은 dataset 전체에서 한쪽 체형에 치우치지 않도록 균형을 맞춘다.

Pose 선택 규칙:

- avatar를 불러왔을 때의 기본 A pose를 기준 pose로 사용한다.
- pose variation은 어깨 관절만 작게 변경한다.
- 어깨 관절 회전은 random으로 주되, 큰 움직임은 금지한다.
- 권장 범위는 기본 A pose 기준 약 `-5도 ~ +5도`이다.
- 팔 전체가 크게 올라가거나 내려가서 garment drape 분포가 비정상적으로 바뀌는 pose는 제외한다.

## Core Rules

- Stage 1은 `dataset/input/fabrics/*.zfab` 원본 fabric과 `dataset/input/garments/**/*.zprj`를 조합한다.
- Output relative sample path는 fabric, garment, body variant, pose 정보를 구분할 수 있어야 한다.
- 예: `fabric_012/short_sleeve_003/body_f_size2_pose017`
- Stage 2 body proxy는 body variant별로 한 번 생성한다.

## Output Structure

```text
dataset/
  01_draped_garments/
    fabric_012/
      short_sleeve_003/
        body_f_size2_pose017/
          obj.obj
          obj.mtl
          summary.json
      ...
    dataset_summary.json
  02_body_proxy_gt/
    body_f_size2/
      avatar.obj
      avatar_meta.json
      proxy/
        body_proxy_gt.json
        body_proxy_tensor.npy
        slices_png/
    ...
  03_blender_multiview/
    fabric_012/
      short_sleeve_003/
        body_f_size2_pose017/
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
    fabric_012/
      short_sleeve_003/
        body_f_size2_pose017/
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
