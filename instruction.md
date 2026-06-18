# 다이텍 전달용 CLO Garment Dataset 제작 스펙

## 0. 목적

본 데이터셋의 목적은 **3DGS 생성 전 단계**에서 사용할 수 있는 CLO 기반 합성 의류 데이터를 대량 제작하는 것이다.
각 샘플은 **bending 물성 차이로 인해 drape 형상이 달라지는지** 확인 가능해야 하며, 최종적으로 다음 데이터를 제공해야 한다.

- Multi-view RGB 이미지
- 카메라 파라미터
- COLMAP 형식 camera files
- Draped garment `.zprj`
- Exported OBJ / MTL / texture
- 각 샘플의 material metadata `.json`

> 현재 단계에서는 **3DGS 학습은 수행하지 않는다.** 3DGS는 이후 연구자가 별도로 학습한다.

---

## 1. 최종 제작 규모

### 1.1 권장 large-scale 구성

| 항목 | 값 | 설명 |
|---|---:|---|
| 의류 카테고리 수 | 5개 | 티셔츠, 셔츠(블라우스), 긴바지, 스커트, 드레스 |
| 카테고리당 garment 수 | 10개 이상 | 서로 다른 패턴/디자인의 CLO garment |
| 전체 garment 수 | 50개 이상 | `5 categories × 10 garments` |
| Avatar | 2개 | CLO 기본 Male / Female 마네킹 |
| Pose | 1개 | 기본 A pose 고정. pose variation 없음 |
| Bending 샘플 수 | 10개 | UI 기준 0~100 uniform sampling |
| Garment당 drape 수 | 20개 | `2 avatars × 10 bending` |
| 전체 draped sample 수 | 1,000개 | `5 × 10 × 2 × 10` |
| Sample당 render view | 48장 | 구면 카메라 샘플링 |
| 전체 render image 수 | 48,000장 | `1,000 samples × 48 views` |

### 1.2 최소 납품 기준

| 항목 | 최소 기준 |
|---|---:|
| 전체 garment 수 | 50개 이상 |
| 전체 draped sample 수 | 1,000개 목표 |
| 최종 유효 sample 수 | 1,000개 이상 |
| 최종 유효 image 수 | 46,000장 이상 |

실패 샘플은 삭제하지 말고 `failure_report.csv`에 원인을 기록한다.

---

## 2. 제작할 의류 종류

| Category ID | 옷 종류 | 필수 개수 | 권장 디자인 variation |
|---|---|---:|---|
| `tshirt` | 티셔츠 | 10개 이상 | 반팔/긴팔, loose/regular fit, neck shape 변화 |
| `shirt` | 셔츠/블라우스 | 10개 이상 | 버튼 셔츠, 블라우스, 오버핏/슬림핏 |
| `pants` | 바지 | 10개 이상 | 긴바지, 와이드 팬츠, 슬림 팬츠 |
| `skirt` | 스커트 | 10개 이상 | A-line, pencil, pleated, short/long |
| `dress` | 드레스 | 10개 이상 | sleeveless, short sleeve, long dress, loose/tight |

### 주의사항

- 각 category 내부에서 **패턴 구조가 너무 비슷한 garment만 반복하지 않는다.**
- 동일한 garment에서 색/텍스처만 바꾼 것은 서로 다른 garment로 계산하지 않는다.
- 목표는 texture variation이 아니라 **drape shape variation**이다.
- bending 외의 파라미터는 고정한다.

---

## 3. Avatar / Pose 조건

| 항목 | 조건 |
|---|---|
| Avatar | CLO 기본 Male, CLO 기본 Female |
| Pose | 기본 pose 고정 |
| Body shape variation | 없음 |
| Motion / animation | 없음 |
| 목적 | 물성 변화에 따른 정적 drape 차이만 관찰 |

### 처리 규칙

- 하나의 garment는 가능한 경우 **Male/Female 두 마네킹 모두에 drape**한다.
- 특정 garment가 한쪽 avatar에서 심하게 깨지거나 착장 자체가 불가능하면 해당 샘플은 실패 처리한다.

---

## 4. Bending 물성 샘플링 규칙

### 4.1 조작할 물성

| 물성 | 조작 여부 | 설명 |
|---|---|---|
| Bending-Warp | 변경 | UI 기준 0~100 |
| Bending-Weft | 변경 | UI 기준 0~100 |
| Stretch | 고정 | base fabric 값 유지 |
| Shear | 고정 | base fabric 값 유지 |
| Density / Mass | 고정 | base fabric 값 유지 |
| Thickness | 고정 | base fabric 값 유지 |
| Texture / Color | 고정 | 같은 garment 내에서 고정 |

본 데이터셋에서는 **Bending-Warp와 Bending-Weft만 paired 방식으로 동시에 변경**한다.
즉, 한 샘플에서 `Bending-Warp UI = Bending-Weft UI`로 둔다.

### 4.2 UI 값

| Sample index | Bending-Warp UI | Bending-Weft UI |
|---:|---:|---:|
| 0 | 0 | 0 |
| 1 | 11 | 11 |
| 2 | 22 | 22 |
| 3 | 33 | 33 |
| 4 | 44 | 44 |
| 5 | 56 | 56 |
| 6 | 67 | 67 |
| 7 | 78 | 78 |
| 8 | 89 | 89 |
| 9 | 100 | 100 |

정확한 실수값을 저장할 수 있으면 아래 값을 metadata에 함께 기록한다.

```text
0.00, 11.11, 22.22, 33.33, 44.44, 55.56, 66.67, 77.78, 88.89, 100.00
```

### 4.3 Material metadata 필수 기록

각 bending sample마다 `*.material.json`에 아래 정보를 저장한다.

| Key | 예시 |
|---|---|
| `category_id` | `tshirt` |
| `garment_id` | `tshirt_000` |
| `avatar_id` | `male` 또는 `female` |
| `pose_id` | `default_pose` |
| `bending_sample_index` | `000` |
| `bending_warp_ui` | `44` |
| `bending_weft_ui` | `44` |
| `bending_warp_internal` | CLO 내부 실제 값, 가능하면 기록 |
| `bending_weft_internal` | CLO 내부 실제 값, 가능하면 기록 |
| `base_fabric_zfab` | 사용한 base fabric path |
| `base_garment_zprj` | 사용한 base garment path |
| `clo_version` | 사용한 CLO 버전 |
| `simulation_steps` | `300` |

---

## 5. Rendering 조건

| 항목 | 값 |
|---|---:|
| Render view 수 | 48 |
| Resolution | 512 × 512 |
| Camera sampling | garment 중심을 바라보는 구면 샘플링 |
| Camera radius | 자동 또는 `radius_scale = 3.0` 기준 |
| Lens | 50 mm |
| Sensor width | 36 mm |
| Render samples | 128 |
| Output format | PNG |
| Lighting | 고정 |
| Background / world strength | 고정 |

### 렌더링 품질 조건

- **모든 view에서 옷이 화면 밖으로 잘리지 않아야 한다.**
- 옷 전체가 보이도록 camera radius를 조정한다.
- sample 간 카메라 위치, 조명, 해상도는 동일하게 유지한다.
- bending 값만 바뀌어야 하므로 texture, lighting, camera 변화는 최소화한다.

---

## 6. 폴더 구조

기존 pipeline 구조를 유지하기 위해 **garment/avatar 단위로 output root를 나누어 실행**한다.

권장 최상위 구조:

```text
DyeTech_CLO_Garment_Dataset/
  dataset_index.csv
  dataset_index.json
  failure_report.csv
  production_summary.json

  tshirt/
    tshirt_000/
      male/
        dataset_pipeline_config.json
        01_fabric_bending/
        02_draped_garments/
        03_manual_obj_exports/
        04_blender_multiview/
        05_3dgs/
      female/
        dataset_pipeline_config.json
        01_fabric_bending/
        02_draped_garments/
        03_manual_obj_exports/
        04_blender_multiview/
        05_3dgs/

  shirt/
  pants/
  skirt/
  dress/
```

각 `garment/avatar` 폴더 내부는 현재 코드의 output 구조를 그대로 따른다.

```text
01_fabric_bending/
  base_000.zfab
  base_000.material.json
  ...
  base_009.zfab
  base_009.material.json
  summary_bending_sampling.json

02_draped_garments/
  000_base_000/
    draped_garment.zprj
    summary.json
  ...
  009_base_009/
    draped_garment.zprj
    summary.json
  dataset_summary.json

03_manual_obj_exports/
  000_base_000/
    obj.obj
    obj.mtl
    obj_diffuse.png
    obj_normal.png

04_blender_multiview/
  000_base_000/
    images/
      000.png
      ...
      047.png
    camera_parameters.json
    sparse/0/
      cameras.txt
      images.txt
      points3D.txt
      points3D.ply
    mesh_vertices.csv
    dataset_summary.json

05_3dgs/
```

`05_3dgs/`는 비워 두어도 된다.

---

## 7. Config 수정 지침

현재 pipeline config에서 large-scale 제작을 위해 반드시 확인할 값은 아래와 같다.

| Config key | 현재/권장 값 | 설명 |
|---|---:|---|
| `fabric_sampler.sample_count` | `10` | bending 파라미터를 몇 단계로 변경하는지 |
| `fabric_sampler.sample_mode` | `paired` | Warp/Weft bending을 같은 UI 값으로 변경 |
| `clo_simulation.sim_steps` | `300` | 기본 유지 |
| `clo_simulation.save_sim_zprj` | `true` | draped `.zprj` 저장 |
| `clo_simulation.export_obj` | `false` | OBJ는 CLO UI에서 수동 export |
| `clo_simulation.skip_render` | `true` | CLO 내 렌더는 사용하지 않음 |
| `blender_render.render_all_samples` | `true` | 모든 OBJ 샘플 렌더링 |
| `blender_render.num_views` | `48` | sample당 48 views |
| `blender_render.resolution` | `512` | 512×512 image |
| `3dgs_training.enabled` | `false` | 3DGS 학습 미수행 |

권장 config override:

```json
{
  "fabric_sampler": {
    "sample_count": 10,
    "sample_mode": "paired"
  },
  "clo_simulation": {
    "sim_steps": 300,
    "save_sim_zprj": true,
    "skip_render": true,
    "export_obj": false
  },
  "blender_render": {
    "render_all_samples": true,
    "num_views": 48,
    "resolution": 512
  },
  "3dgs_training": {
    "enabled": false
  }
}
```

---

## 8. 실행 순서

| Step | 작업 | 실행 위치 | 결과 |
|---:|---|---|---|
| 1 | Fabric bending sample 생성 | CLO Python Script Editor | `01_fabric_bending/base_*.zfab`, `*.material.json` |
| 2 | CLO simulation 후 draped ZPRJ 저장 | CLO Python Script Editor | `02_draped_garments/*/draped_garment.zprj` |
| 3 | Draped ZPRJ에서 OBJ 수동 export | CLO UI | `03_manual_obj_exports/*/obj.obj` |
| 4 | Blender multi-view rendering | Blender Python | `04_blender_multiview/*/images`, camera files |
| 5 | 3DGS 학습 | 실행하지 않음 | 빈 `05_3dgs/` 유지 |

---

## 9. OBJ 수동 export 규칙

CLO에서 `draped_garment.zprj`를 열고 OBJ를 수동 export한다.

| 항목 | 규칙 |
|---|---|
| 폴더명 | `02_draped_garments/<sample>`과 동일해야 함 |
| OBJ 파일명 | `obj.obj` |
| MTL 파일명 | `obj.mtl` |
| Diffuse texture | `obj_diffuse.png` 또는 `obj_diffuse_1001.png` |
| Normal texture | `obj_normal.png` 또는 `obj_normal_1001.png` |
| UV | pattern이 서로 겹치지 않도록 0~1 범위 내 배치 |
| Export scale | `1%` |

---

## 10. 품질 검수 기준

### 10.1 샘플 단위 검수

각 sample은 아래 조건을 만족해야 한다.

| 검수 항목 | 통과 기준 |
|---|---|
| Material file | `*.material.json` 존재 |
| Draped ZPRJ | `draped_garment.zprj` 존재 |
| OBJ | `obj.obj`, `obj.mtl` 존재 |
| Texture | diffuse texture 존재, normal texture 가능하면 포함 |
| Render images | 정확히 48장 존재 |
| Camera metadata | `camera_parameters.json` 존재 |
| COLMAP files | `cameras.txt`, `images.txt`, `points3D.txt`, `points3D.ply` 존재 |
| Geometry | 심한 찢어짐, 폭발, 비정상 접힘 없음 |
| Visibility | 모든 view에서 garment가 화면 내에 있음 |

### 10.2 Bending variation 검수

각 garment/avatar 조합마다 bending 10개 결과를 비교한다.

| 비교 | 확인할 점 |
|---|---|
| UI 0 vs UI 100 | drape 차이가 시각적으로 보여야 함 |
| UI 증가 순서 | 낮은 bending은 더 흐물거리고, 높은 bending은 더 빳빳해야 함 |
| 동일 garment 내 texture | bending만 바뀌고 texture/camera/lighting은 동일해야 함 |
| simulation failure | 값이 바뀌어도 형상이 완전히 동일하면 실패 의심 |


---

## 11. Dataset index 파일

최종 납품 시 `dataset_index.csv`와 `dataset_index.json`을 함께 제공한다.

필수 column:

| Column | 설명 |
|---|---|
| `sample_uid` | 전체 데이터셋에서 unique한 ID |
| `category_id` | `tshirt`, `shirt`, `pants`, `skirt`, `dress` |
| `garment_id` | `tshirt_000` 등 |
| `avatar_id` | `male` 또는 `female` |
| `pose_id` | `default_pose` |
| `bending_sample_index` | `000`~`009` |
| `bending_warp_ui` | 0~100 |
| `bending_weft_ui` | 0~100 |
| `draped_zprj_path` | `.zprj` 상대경로 |
| `obj_path` | `.obj` 상대경로 |
| `images_dir` | multi-view image 폴더 상대경로 |
| `camera_json_path` | `camera_parameters.json` 상대경로 |
| `colmap_dir` | `sparse/0` 상대경로 |
| `material_json_path` | material metadata 상대경로 |
| `status` | `success` 또는 `failed` |
| `failure_reason` | 실패 시 원인 |

---

## 12. 납품 파일 목록

최종 납품에는 아래 항목이 모두 포함되어야 한다.

| 파일/폴더 | 필수 여부 | 설명 |
|---|---|---|
| `dataset_index.csv` | 필수 | 전체 sample index |
| `dataset_index.json` | 필수 | 전체 sample index JSON 버전 |
| `production_summary.json` | 필수 | 전체 제작 개수, 실패 개수, config 요약 |
| `failure_report.csv` | 필수 | 실패 샘플 및 원인 |
| `01_fabric_bending/` | 필수 | bending별 `.zfab`, material json |
| `02_draped_garments/` | 필수 | draped `.zprj` |
| `03_manual_obj_exports/` | 필수 | OBJ/MTL/texture |
| `04_blender_multiview/` | 필수 | 48-view image, camera files |
| `05_3dgs/` | 선택 | 현재는 비워둠(연세대에서 학습) |
| `preview_contact_sheet/` | 권장 | 빠른 시각 검수용 |

---

## 13. 먼저 제작할 pilot set

전체 제작 전에 아래 pilot set을 먼저 만든다.

| 항목 | 값 |
|---|---:|
| Category | 티셔츠 1개, 드레스 1개 |
| Garment 수 | 2개 |
| Avatar | Male/Female |
| Bending | 10개 |
| Draped sample | 40개 |
| Render image | 1,920장 |

Pilot set에서 확인할 것:

1. bending UI 값이 실제 material 값에 반영되는지
2. UI 0과 UI 100 사이 drape 차이가 보이는지
3. OBJ export scale 1%가 Blender render와 맞는지
4. 48-view camera parameter가 3DGS 학습 입력으로 바로 사용 가능한지
5. 폴더명과 `dataset_index.csv`가 서로 일치하는지

Pilot set이 통과한 뒤 전체 1,000 sample 제작을 진행한다.

---

## 14. 하지 말아야 할 것

- Pose variation을 넣지 않는다.
- bending 외 다른 물성을 바꾸지 않는다.
- 같은 garment에서 texture/color를 바꾸지 않는다.
- 카메라 개수, 해상도, 렌즈 값을 샘플마다 다르게 바꾸지 않는다.

---

## 15. 핵심 요약

| 항목 | 최종 요청 |
|---|---|
| 옷 종류 | 5개: 티셔츠, 셔츠/블라우스, 바지, 스커트, 드레스 |
| Garment 개수 | category당 10개 이상, 총 50개 이상 |
| Avatar | CLO 기본 Male/Female |
| Pose | 기본 pose 고정 |
| 물성 변화 | Bending-Warp/Weft만 변경 |
| Bending sample | 10개, UI 0~100 uniform |
| Drape 결과 | 총 1,000개 목표 |
| Render | sample당 48-view, 512×512 |
| 전체 이미지 | 48,000장 목표 |
| 3DGS | 연세대에서 학습 |
| 최종 산출물 | multi-view images, camera parameters, COLMAP files, OBJ, ZPRJ, material JSON |
