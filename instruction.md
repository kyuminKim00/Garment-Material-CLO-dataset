# 다이텍 전달용 CLO Garment Dataset 제작 스펙

## 0. 목적

본 데이터셋의 목적은 **3DGS 생성 전 단계**에서 사용할 수 있는 CLO 기반 합성 의류 데이터를 대량 제작하는 것이다.
각 샘플은 **bending 물성 차이로 인해 drape 형상이 달라지는지** 확인 가능해야 하며, 최종적으로 다음 데이터가 필요.

- Multi-view RGB 이미지
- 카메라 파라미터 (COLMAP 형식 camera files)
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
| Body model | 2개 | Male / Female base `.zprj`를 별도 입력으로 사용 |
| Pose | 1개 | 기본 A pose 고정. pose variation 없음 |
| Garment당 fabric 수 | 5개 이상 | 같은 garment geometry에 여러 base fabric `.zfab` 적용 |
| Fabric당 bending 샘플 수 | 10개 이상 권장(config 지정) | `fabric_sampler.sample_count`로 조절 |
| Garment당 drape 수 | 200개 이상 | `2 body models × 5 fabrics × 10 bending` 기준 |
| 전체 draped sample 수 | 10,000개 이상 | `5 × 10 garments × 2 bodies × 5 fabrics × 10 bending` 기준 |
| Sample당 render view | 48장 | 구면 카메라 샘플링 |
| 전체 render image 수 | 240,000장 이상 | `5,000 samples × 48 views` |

### 1.2 최소 충족 기준

| 항목 | 최소 기준 |
|---|---:|
| 전체 garment 수 | 50개 이상 |
| Garment당 fabric 수 | 5개 이상 |
| 전체 draped sample 수 | 5,000개 목표 |
| 최종 유효 sample 수 | 5,000개 이상 |
| 최종 유효 image 수 | 240,000장 이상 |

실패 샘플은 삭제하지 말고 `failure_report.csv`에 원인을 기록한다.

---

## 2. 제작할 의류 종류
bending의 변화가 잘드러나기 위해서는 옷 자체가 몸에 밀착되기 보단 loose 해야함.
garment를 고를 때 가능하면 loose한 옷 권장

| Category ID | 옷 종류 | 필수 개수 | 권장 디자인 variation |
|---|---|---:|---|
| `tshirt` | 티셔츠 | 10개 이상 | 반팔/긴팔, loose/regular fit, neck shape 변화 |
| `shirt` | 셔츠/블라우스 | 10개 이상 | 버튼 셔츠, 블라우스, 오버핏/슬림핏 |
| `pants` | 바지 | 10개 이상 | 긴바지, 와이드 팬츠 |
| `skirt` | 스커트 | 10개 이상 | short/long |
| `dress` | 드레스 | 10개 이상 | sleeveless, short sleeve, long dress, loose/tight |

### 주의사항

- 각 category 내부에서 **패턴 구조가 너무 비슷한 garment만 반복하지 않는다.**
- 동일한 garment에서 색/텍스처만 바꾼 것은 서로 다른 garment로 계산하지 않는다.
- 목표는 단순 texture variation이 아니라 **fabric 물성 및 bending 변화에 따른 drape shape variation**이다.
- 같은 base fabric에서 bending sample을 만들 때는 bending 외의 파라미터를 고정한다.

### Fabric 선택 규칙

- 각 garment에 대해 **서로 다른 fabric을 5개 이상** 사용한다.
- fabric texture가 서로 너무 비슷한 것만 반복하지 않는다. 색, weave/knit pattern, roughness, normal/bump 느낌이 구분되는 fabric을 섞는다.
- 투명하거나 반투명한 fabric은 사용하지 않는다. 내부 body/garment layer가 비쳐 보이면 제외한다.
- 주름, 접힘, bending 차이가 시각적으로 잘 드러나는 fabric을 우선한다.
- 너무 반짝이거나 과도하게 noisy한 texture는 geometry wrinkle 판별을 방해하면 제외한다.
- 같은 base fabric에서 생성한 bending variants 안에서는 texture/color/density/thickness/stretch/shear를 고정하고 bending만 바꾼다.

---

## 3. Body Model / Pose 조건

| 항목 | 조건 |
|---|---|
| Body model | Male base `.zprj`, Female base `.zprj` |
| Pose | 기본 pose 고정 |
| Body shape variation | 없음 |
| Motion / animation | 없음 |
| 목적 | 물성 변화에 따른 정적 drape 차이만 관찰 |

### 처리 규칙

- 하나의 garment는 가능한 경우 **Male/Female 두 body model 모두에 drape**한다.
- 입력 구조는 `input/garments/female/base.zprj`, `input/garments/male/base.zprj`처럼 body별 폴더를 분리한다.
- fabric은 male/female로 나누지 않는다. 모든 body model이 `input/fabrics/*.zfab`의 같은 fabric pool을 공유한다.
- 특정 garment가 한쪽 body model에서 심하게 깨지거나 착장 자체가 불가능하면 해당 샘플은 실패 처리한다.

---

## 4. Bending 물성 샘플링 규칙

### 4.1 조작할 물성

| 물성 | 조작 여부 | 설명 |
|---|---|---|
| Bending-Warp | 변경 | UI 기준 0~100 |
| Bending-Weft | 변경 | UI 기준 0~100 |
| Stretch | 고정 | 각 base fabric 값 유지 |
| Shear | 고정 | 각 base fabric 값 유지 |
| Density / Mass | 고정 | 각 base fabric 값 유지 |
| Thickness | 고정 | 각 base fabric 값 유지 |
| Texture / Color | 고정 | 같은 base fabric의 bending variants 안에서 고정 |

본 데이터셋에서는 **Bending-Warp와 Bending-Weft만 paired 방식으로 동시에 변경**한다.
즉, 한 샘플에서 `Bending-Warp UI = Bending-Weft UI`로 둔다.

### 4.2 UI 값 선택

Bending은 UI 0~100 전체를 단순 uniform으로 찍지 않는다. 낮은 UI 구간에서는 drape 차이가 잘 안 보이고, 높은 UI 구간에서 stiffness 차이가 더 뚜렷하므로 **구간별 random bucket sampling**을 사용한다.

기본 bucket weight:

| UI 구간 | weight | 목적 |
|---:|---:|---|
| 0 anchor | 고정 1개 | 가장 부드러운 기준 |
| 0~20 | 1 | 낮은 bending 일부만 확인 |
| 20~50 | 2 | 중저 bending 영역 |
| 50~70 | 2 | 변화가 보이기 시작하는 영역 |
| 70~100 | 3 | drape 차이가 크게 보이는 영역을 더 촘촘히 샘플링 |
| 100 anchor | 고정 1개 | 가장 빳빳한 기준 |

`fabric_sampler.sample_count`가 최종 bending 개수를 결정한다. `sample_bins[*].count`는 고정 개수가 아니라 bucket weight로 사용한다.

- `sample_count = 2`이면 UI `0`, `100`만 생성한다.
- 기본 `sample_count = 10`이면 0/100 anchor를 포함해 총 10개 bending을 생성한다.
- 구간 내부 값은 random jitter로 뽑아 classification bin처럼 고정값이 반복되지 않게 한다.
- 하나의 bending sample에서는 Warp/Weft/Bias bending을 같은 UI level로 묶어 변경한다.
- metadata에는 실제 `ui.bending_warp`, `ui.bending_weft`, `ui.bending_bias`, raw/internal 값을 모두 기록한다.

### 4.3 Material metadata 필수 기록

각 bending sample마다 `*.material.json`에 아래 정보를 저장한다.

| Key | 예시 |
|---|---|
| `category_id` | `tshirt` |
| `garment_id` | `tshirt_000` |
| `body_id` | `male` 또는 `female` |
| `fabric_id` | `fabric_000` |
| `bend_id` | `bend_000` |
| `pose_id` | `default_pose` |
| `bending_sample_index` | `000` |
| `bending_warp_ui` | `44` |
| `bending_weft_ui` | `44` |
| `bending_warp_internal` | CLO 내부 실제 값, 가능하면 기록 |
| `bending_weft_internal` | CLO 내부 실제 값, 가능하면 기록 |
| `source_zfab` | 사용한 base fabric path |
| `garment_zprj` | 사용한 male/female base garment path |
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

현재 pipeline은 하나의 `output_dir` 안에서 body model, fabric, bending 축을 모두 관리한다.
fabric variant는 male/female로 나누지 않고 공통으로 생성하며, CLO drape 이후 결과만 body model별로 분리한다.

권장 최상위 구조:

```text
DyeTech_CLO_Garment_Dataset/
  dataset_index.csv
  dataset_index.json
  failure_report.csv
  production_summary.json

  tshirt/
    tshirt_000/
      dataset_config.json
      input/
        garments/
          female/
            base.zprj
          male/
            base.zprj
        fabrics/
          fabric_000.zfab
          fabric_001.zfab
          ...
          fabric_009.zfab
      01_fabric_bending/
      02_draped_garments/
      03_blender_multiview/
      04_3dgs/

  shirt/
  pants/
  skirt/
  dress/
```

각 garment 폴더 내부는 아래 output 구조를 따른다.

```text
01_fabric_bending/
  fabric_000/
    bend_000/
      fabric.zfab
      material.json
    bend_001/
      fabric.zfab
      material.json
  fabric_001/
    bend_000/
      fabric.zfab
      material.json
  summary_bending_sampling.json

02_draped_garments/
  female/
    fabric_000/
      bend_000/
        draped_garment.zprj
        obj.obj
        obj.mtl
        <CLO-exported texture files>
        material.json
        summary.json
  male/
    fabric_000/
      bend_000/
        draped_garment.zprj
        obj.obj
        obj.mtl
        <CLO-exported texture files>
        material.json
        summary.json
  dataset_summary.json

03_blender_multiview/
  female/
    fabric_000/
      bend_000/
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

04_3dgs/
```

`04_3dgs/`는 비워 두어도 된다.

---

## 7. Config 수정 지침

현재 pipeline config에서 large-scale 제작을 위해 반드시 확인할 값은 아래와 같다.

| Config key | 현재/권장 값 | 설명 |
|---|---:|---|
| `inputs.input_dir` | `input` | garment/fabric 입력 루트 |
| `inputs.garments_dir` | `input/garments` | `female/base.zprj`, `male/base.zprj` 위치 |
| `inputs.fabrics_dir` | `input/fabrics` | garment당 5개 이상의 `.zfab` 입력 위치 |
| `fabric_sampler.sample_count` | `10` | fabric당 bending variant 개수. config로 변경 가능 |
| `fabric_sampler.sample_mode` | `paired` | Warp/Weft/Bias bending을 같은 UI 값으로 변경 |
| `fabric_sampler.sample_distribution` | `ui_bucket_jittered` | bending 차이가 잘 보이도록 구간별 random sampling |
| `fabric_sampler.preserve_bending_v2_ratio` | `false` | `_v2` 포함 bending 내부 필드를 같은 raw 값으로 변경 |
| `fabric_sampler.patch_bending_bias` | `true` | Warp/Weft와 함께 Bias bending도 같은 bending level로 변경 |
| `fabric_sampler.bias_fields` | `["fBhK", "fBhK_v2", "fBLeftShearK", "fBLeftShearK_v2", "fBRightShearK", "fBRightShearK_v2"]` | CLO `.fab` 내부 Bias bending 후보 필드 |
| `clo_simulation.sim_steps` | `300` | 기본 유지 |
| `clo_simulation.save_sim_zprj` | `true` | draped `.zprj` 저장 |
| `clo_simulation.export_obj` | `true` | simulation 후 `02_draped_garments` sample 폴더에 OBJ/MTL/texture 자동 export |
| `clo_simulation.skip_render` | `true` | CLO 내 렌더는 사용하지 않음 |
| `blender_render.render_all_samples` | `true` | 모든 OBJ 샘플 렌더링 |
| `blender_render.num_views` | `48` | sample당 48 views |
| `blender_render.resolution` | `512` | 512×512 image |
| `3dgs_training.enabled` | `false` | 3DGS 학습 미수행 |

권장 config override:

```json
{
  "inputs": {
    "input_dir": "input",
    "garments_dir": "input/garments",
    "fabrics_dir": "input/fabrics"
  },
  "naming": {
    "fabric_variant_dir_template": "{fabric_id}/{bend_id}",
    "sample_dir_template": "{garment_id}/{fabric_id}/{bend_id}",
    "fabric_file_template": "fabric.zfab",
    "material_json_template": "material.json"
  },
  "fabric_sampler": {
    "sample_count": 10,
    "sample_mode": "paired",
    "sample_distribution": "ui_bucket_jittered",
    "sample_bins": [
      { "min": 0.0, "max": 20.0, "count": 1 },
      { "min": 20.0, "max": 50.0, "count": 2 },
      { "min": 50.0, "max": 70.0, "count": 2 },
      { "min": 70.0, "max": 100.0, "count": 3 }
    ],
    "preserve_bending_v2_ratio": false,
    "patch_bending_bias": true,
    "bias_fields": ["fBhK", "fBhK_v2", "fBLeftShearK", "fBLeftShearK_v2", "fBRightShearK", "fBRightShearK_v2"]
  },
  "clo_simulation": {
    "sim_steps": 300,
    "save_sim_zprj": true,
    "skip_render": true,
    "export_obj": true
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
| 0 | 입력 파일 배치 | 파일 시스템 | `input/garments/female/base.zprj`, `input/garments/male/base.zprj`, `input/fabrics/*.zfab` |
| 1 | Fabric bending sample 생성 | CLO Python Script Editor 또는 Python | `01_fabric_bending/<fabric_id>/<bend_id>/fabric.zfab`, `material.json` |
| 2 | CLO simulation 후 draped ZPRJ + OBJ export | CLO Python Script Editor | `02_draped_garments/<male/female>/<fabric_id>/<bend_id>/draped_garment.zprj`, `obj.obj`, `obj.mtl`, texture |
| 3 | Blender multi-view rendering | Blender Python | `03_blender_multiview/<male/female>/<fabric_id>/<bend_id>/images`, camera files |
| 4 | 3DGS 학습 | 실행하지 않음 | 빈 `04_3dgs/` 유지 |

---

## 9. 01-03 한번에 실행

`scripts/run_stages_01_03.py`는 CLO를 새로 실행하지 않는다. CLO Python Script Editor에 코드를 붙여넣어 실행하는 용도다.

동작 순서:

1. 현재 CLO Python 프로세스에서 `clo_fab_sampler.py` 실행
2. 현재 CLO Python 프로세스에서 `clo_make_dataset.py` 실행
3. Blender를 `--background`로 실행해서 `blender_render.py` 실행

기본 config 경로는 스크립트 안에 하드코딩되어 있다.

```python
CONFIG_JSON_PATH = r"C:\Users\CGnA\Desktop\CLO\dataset_config.json"
```

Blender가 `PATH`에 없으면 `--blender` 인자로 Blender 실행 파일 경로를 넘긴다.

---

## 10. OBJ 자동 export 규칙

`scripts/clo_make_dataset.py`가 simulation 직후 같은 sample 폴더에 OBJ를 자동 export한다.

| 항목 | 규칙 |
|---|---|
| 폴더명 | `02_draped_garments/<body_id>/<fabric_id>/<bend_id>` |
| OBJ 파일명 | `obj.obj` |
| MTL 파일명 | `obj.mtl` |
| Texture | CLO export가 생성하고 `obj.mtl`이 참조하는 texture 파일 |
| 후처리 | texture 복사, MTL rewrite, UV rewrite를 하지 않음 |
| Export scale | `1%` |

---

## 11. 품질 검수 기준

### 11.1 샘플 단위 검수

각 sample은 아래 조건을 만족해야 한다.

| 검수 항목 | 통과 기준 |
|---|---|
| Material file | `*.material.json` 존재 |
| Draped ZPRJ | `draped_garment.zprj` 존재 |
| OBJ | `obj.obj`, `obj.mtl` 존재 |
| Texture | diffuse texture 존재, normal texture 가능하면 포함 |
| Fabric diversity | 같은 garment에 쓰인 fabric들이 서로 다른 texture/재질감을 가져야 함 |
| Non-transparent fabric | 투명/반투명 fabric이 아니어야 함 |
| Wrinkle visibility | 주름과 접힘이 이미지에서 잘 보여야 함 |
| Render images | 정확히 48장 존재 |
| Camera metadata | `camera_parameters.json` 존재 |
| COLMAP files | `cameras.txt`, `images.txt`, `points3D.txt`, `points3D.ply` 존재 |
| Geometry | 심한 찢어짐, 폭발, 비정상 접힘 없음 |
| Visibility | 모든 view에서 garment가 화면 내에 있음 |

### 11.2 Bending variation 검수

각 garment/body/fabric 조합마다 `fabric_sampler.sample_count`개 bending 결과를 비교한다.

| 비교 | 확인할 점 |
|---|---|
| UI 0 vs UI 100 | drape 차이가 시각적으로 보여야 함 |
| UI 증가 순서 | 낮은 bending은 더 흐물거리고, 높은 bending은 더 빳빳해야 함 |
| 동일 garment/body/fabric 내 texture | bending만 바뀌고 texture/camera/lighting은 동일해야 함 |
| simulation failure | 값이 바뀌어도 형상이 완전히 동일하면 실패 의심 |


---

## 12. Dataset index 파일

최종 납품 시 `dataset_index.csv`와 `dataset_index.json`을 함께 제공한다.

필수 column:

| Column | 설명 |
|---|---|
| `sample_uid` | 전체 데이터셋에서 unique한 ID |
| `category_id` | `tshirt`, `shirt`, `pants`, `skirt`, `dress` |
| `garment_id` | `tshirt_000` 등 |
| `body_id` | `male` 또는 `female` |
| `fabric_id` | `fabric_000` 등 |
| `bend_id` | `bend_000` 등 |
| `pose_id` | `default_pose` |
| `bending_sample_index` | `000`부터 `sample_count - 1`까지 |
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

## 13. 납품 파일 목록

최종 납품에는 아래 항목이 모두 포함되어야 한다.

| 파일/폴더 | 필수 여부 | 설명 |
|---|---|---|
| `dataset_index.csv` | 필수 | 전체 sample index |
| `dataset_index.json` | 필수 | 전체 sample index JSON 버전 |
| `production_summary.json` | 필수 | 전체 제작 개수, 실패 개수, config 요약 |
| `failure_report.csv` | 필수 | 실패 샘플 및 원인 |
| `01_fabric_bending/` | 필수 | bending별 `.zfab`, material json |
| `02_draped_garments/` | 필수 | draped `.zprj`, OBJ/MTL/texture, material json |
| `03_blender_multiview/` | 필수 | 48-view image, camera files |
| `04_3dgs/` | 선택 | 현재는 비워둠(연세대에서 학습) |
| `preview_contact_sheet/` | 권장 | 빠른 시각 검수용 |

---

## 14. 먼저 제작할 pilot set

전체 제작 전에 아래 pilot set을 먼저 만든다.

| 항목 | 값 |
|---|---:|
| Category | 티셔츠 1개, 드레스 1개 |
| Garment 수 | 2개 |
| Body model | Male/Female |
| Fabric | garment당 5개 이상 |
| Bending | config 기준. 기본 10개 |
| Draped sample | 400개 | 
| Render image | 19,200장 |

Pilot set에서 확인할 것:

1. bending UI 값이 실제 material 값에 반영되는지
2. UI 0과 UI 100 사이 drape 차이가 보이는지
3. bucket jittered bending 값들이 50~100 고강성 구간에서 충분한 형태 차이를 만드는지
4. OBJ export scale 1%가 Blender render와 맞는지
5. 48-view camera parameter가 3DGS 학습 입력으로 바로 사용 가능한지 (연세대)
6. 폴더명과 `dataset_index.csv`가 서로 일치하는지

Pilot set이 통과한 뒤 전체 제작을 진행한다.

---

## 15. 하지 말아야 할 것

- Pose variation을 넣지 않는다.
- **투명하거나 반투명한 fabric을 사용하지 않는다.**
- texture가 거의 같은 fabric만 반복해서 fabric pool을 구성하지 않는다.
- 주름/접힘이 잘 보이지 않는 지나치게 밋밋한 fabric만 사용하지 않는다.
- 같은 base fabric의 bending variants 안에서는 bending weft/warp 외 다른 물성을 바꾸지 않는다.
- 같은 base fabric의 bending variants 안에서는 texture/color를 바꾸지 않는다.
- 카메라 개수, 해상도, 렌즈 값을 샘플마다 다르게 바꾸지 않는다.

---

## 16. 핵심 요약

| 항목 | 최종 요청 |
|---|---|
| 옷 종류 | 5개: 티셔츠, 셔츠/블라우스, 바지, 스커트, 드레스 |
| Garment 개수 | category당 10개 이상, 총 50개 이상 |
| Body model | Male/Female base `.zprj` 구분 |
| Fabric | garment당 5개 이상, male/female 공통 fabric pool 사용 |
| Pose | 기본 pose 고정 |
| 물성 변화 | Bending-Warp/Weft만 변경 |
| Bending sample | config로 조절. 기본 10개, bucket jittered sampling |
| Drape 결과 | 총 50,000개 이상 목표 |
| Render | sample당 48-view, 512×512 |
| 전체 이미지 | 240,000장 이상 목표 |
| 3DGS | 연세대에서 학습 |
| 최종 산출물 | multi-view images, camera parameters, COLMAP files, OBJ, ZPRJ, material JSON |
