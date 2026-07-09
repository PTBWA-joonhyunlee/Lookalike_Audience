# addi_data_embedding

`cmp_no`(=addi 캠페인) 광고에 노출·반응(postback)한 유저 중, 실제로 광고주 몰(mall)에서
전환(IP 매칭 기준)했을 가능성이 높은 유저를 임베딩 기반 스코어링으로 가려내는 프로젝트.
2026-04~05 데이터로 학습한 스코어를 2026-06 postback 유저 전체에 매겨서, "전체 postback
유저 전환율 대비 스코어 상위 K%의 전환율"을 백테스트로 검증한다. 원래 SQL/문서 저장소
(`addi_data_embedding`)와 임베딩 모델 코드 저장소(`user-to-ad-encoder`)가 분리돼 있었는데,
이 저장소 하나로 합쳤다(2026-07-08).

> 이 프로젝트는 원래 "아직 postback 없는 신규 유저 중 과거 관심 유저와 행동이 비슷한 유저를
> 찾는"(신규 유저 룩어라이크 타겟팅) 목적으로 시작했다. 그 트랙(T2+ postback tier를 전환으로
> 보는 시드/백테스트)은 2026-07-09에 삭제했다 — 전환 정의를 실제 몰 IP 매칭으로 바꾸면서
> 목적도 "postback 유저 중 실전환 가능성이 높은 유저 선별"로 좁혔기 때문. 신규 유저 타겟팅이
> 다시 필요해지면 같은 임베딩(user_profile/media_sequence, 재학습 불필요)과 스코어링 구조
> 위에서 대상 모집단만 바꿔 재구성하면 된다(과거 구현은 git 히스토리 참고).

## 폴더 구조

```
querys/pipeline/  Athena SQL 8개(01~08) — 이 환경엔 Athena 접근 권한이 없어 콘솔에서 직접 실행 필요 (아래 §1)
querys/athena_validation_queries/  데이터 정합성 검증 — 파이프라인과 별개 트랙, 실행 불필요
embedding/    모델 구조/데이터셋/전처리 정의 (user_profile, media_sequence) — train/inference가 공유
train/        학습 실행 진입점 (아티팩트 저장까지만, 임베딩은 안 뽑음)
inference/    학습된 모델로 재학습 없이 임베딩 추출
scoring/      fusion + lookalike 스코어링(지도학습 분류기, train·infer 분리) + 층화 pool 병합
evaluation/   임베딩 거리 확인(distance.py), 스코어 대비 실제 결과 백테스트(backtest.py)
pipeline/     학습→추론→[층화 pool 병합]→스코어링(→백테스트)을 config 하나로 한번에 실행 (아래 §2-0)
data/         쿼리 결과 CSV / 임베딩 / 모델 아티팩트 (git 추적 안 됨, .gitignore)
docs/         테이블 스키마 레퍼런스 + 모델 아키텍처 스펙
.venv/        Python 3.14 가상환경 (Windows, git 추적 안 됨)
```

## 0. 환경 설정

`.venv`가 이미 있다. 새로 만들어야 하면:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-cpu.txt   # GPU 없는 환경
.venv\Scripts\python.exe -m pip install -r requirements-gpu.txt   # GPU(NVIDIA CUDA) 환경 — cuXXX 태그는 파일 안 주석 참고
```

모든 실행은 저장소 루트에서 `-m` 모듈 실행으로 한다(`train/`, `inference/` 등이 `embedding/`을
가져다 쓰는 패키지라 파일 경로로 직접 실행하면 `ModuleNotFoundError`가 남).

## 1. 데이터 생성 (Athena)

`querys/pipeline/01~08.sql`을 Athena 콘솔에서 순서대로 실행하고, 결과 CSV를 아래 이름으로
`data/raw/`에 저장한다.

| # | SQL | 저장 파일명 | 그레인 | 필요 시점 |
|---|---|---|---|---|
| 01 | `01_pool_profile_apr_may.sql` | `01_pool_profile_apr_may.csv` | 유저 1행, pool(5% 샘플), 4~5월 | 항상 |
| 02 | `02_pool_media_apr_may.sql` | `02_pool_media_apr_may.csv` | 이벤트, pool(5% 샘플), 4~5월 | 항상 |
| 03 | `03_seed_users_apr_may.sql` | `03_seed_users_apr_may.csv` | 유저 1행, 시드(양성) 목록, 4~5월 | 항상 |
| 04 | `04_seed_profile_apr_may.sql` | `04_seed_profile_apr_may.csv` | 유저 1행, 시드 전수(샘플링 없음) | 층화 pool 병합 시 |
| 05 | `05_seed_media_apr_may.sql` | `05_seed_media_apr_may.csv` | 이벤트, 시드 전수(샘플링 없음) | 층화 pool 병합 시 |
| 06 | `06_backtest_labels_jun.sql` | `06_backtest_labels_jun.csv` | ifa 1행, 6월 backtest 라벨 | 백테스트 시 |
| 07 | `07_scoring_target_profile_jun.sql` | `07_scoring_target_profile_jun.csv` | 유저 1행, 6월 postback 유저 전체 | 항상 |
| 08 | `08_scoring_target_media_jun.sql` | `08_scoring_target_media_jun.csv` | 이벤트, 6월 postback 유저 전체 | 항상 |

각 CSV의 컬럼/결측률/분포는 [`docs/pipeline_data_schema.md`](docs/pipeline_data_schema.md) 참고.
왜 이렇게 8단계로 나뉘었는지(전환 정의를 IP 매칭으로 바꾼 배경, 5% 샘플링 문제, 극단적
클래스 불균형 등)는 [`querys/pipeline/README.md`](querys/pipeline/README.md)와
[`docs/_archive/202607091533.md`](docs/_archive/202607091533.md) /
[`docs/_archive/202607091610.md`](docs/_archive/202607091610.md) 참고.

**주의**: 01/02는 데이터량이 너무 커서(캠페인 무필터 2개월치) 유저 단위 5% 샘플링이 걸려
있다(`mod(crc32(...), 100) < 5`, 각 SQL 파일 주석 참고). 03(시드)/04/05(시드 전수)/07/08(6월
스코어링 대상)는 샘플링 없이 전수다.

## 2. 파이프라인 실행 (학습 → 추론 → [층화 pool 병합] → 스코어링 → 백테스트)

### 2-0. 한번에 실행 (권장)

`querys/pipeline/01~03.sql`(층화 pool 병합을 쓰면 04/05도) 결과 CSV를 `data/raw/`에 올려둔
상태라면, 학습→추론→[층화 pool 병합]→스코어링(→백테스트)을 한 커맨드로 실행한다. 개별 단계
함수를 그대로 호출할 뿐이라 산출물 위치는 아래 2-1~2-5의 수동 실행과 동일하다.

```
cp config/pipeline.example.json config/pipeline.json   # 값 채우기 (경로는 기본값 그대로 써도 됨)
.venv\Scripts\python.exe -m pipeline.run_all --config config/pipeline.json
```

`config/pipeline.example.json` 참고. 양성(시드)이 pool의 5% 샘플에 거의 안 남을 만큼
희소하면 `stratify` 블록을 채운다(불필요하면 그 블록 자체를 지운다 — 2-3 참고).
`backtest.enabled`를 `true`로 켜면 백테스트까지, 기본(`false`)이면 스코어링까지만
실행한다(실제 postback이 쌓인 기간에만 백테스트가 의미 있음 — 2-5 참고).

새 기간 스코어링 대상만 다시 추론→스코어링하고 싶을 때(임베딩 모델 재학습 불필요, 2-1 참고)는
`--skip-train`을 붙인다:

```
.venv\Scripts\python.exe -m pipeline.run_all --config config/pipeline.json --skip-train
```

아래 2-1~2-5는 이 파이프라인이 내부적으로 호출하는 개별 단계 — 한 단계만 다시 돌리거나
디버깅할 때 직접 쓴다.

### 2-1. 학습 (최초 1회, 이후 새 기간 데이터가 쌓이면 재실행)

```
.venv\Scripts\python.exe -m train.user_profile   --input data/raw/01_pool_profile_apr_may.csv --output data/models/user_profile_202604_05
.venv\Scripts\python.exe -m train.media_sequence --input data/raw/02_pool_media_apr_may.csv    --output data/models/media_sequence_202604_05
```

GPU가 있는 환경에서는 `--device auto`(기본값, cuda 있으면 자동 사용)/`--device cuda`/`--device cpu`로
지정한다(`--config`로 주는 JSON에도 `"device"` 키로 넣을 수 있음).

모델 구조/필드별 처리 방식은 [`docs/model_architecture.md`](docs/model_architecture.md) 참고.

### 2-2. 추론 (pool=4~5월 전체, target=6월 postback 유저 전체 — 새 데이터가 생기면 매번 반복)

```
.venv\Scripts\python.exe -m inference.user_profile   --input data/raw/01_pool_profile_apr_may.csv   --model-dir data/models/user_profile_202604_05        --output data/embeddings/pool_profile.csv
.venv\Scripts\python.exe -m inference.media_sequence --input data/raw/02_pool_media_apr_may.csv      --model-dir data/models/media_sequence_202604_05      --output data/embeddings/pool_media.csv
.venv\Scripts\python.exe -m inference.user_profile   --input data/raw/07_scoring_target_profile_jun.csv --model-dir data/models/user_profile_202604_05      --output data/embeddings/scoring_target_profile_jun.csv
.venv\Scripts\python.exe -m inference.media_sequence --input data/raw/08_scoring_target_media_jun.csv   --model-dir data/models/media_sequence_202604_05    --output data/embeddings/scoring_target_media_jun.csv
```

### 2-3. 층화 pool 병합 (양성이 5% 샘플에 거의 안 남을 만큼 희소할 때)

학습 pool(01/02)은 5% 샘플이라, 시드(양성)가 원래 적으면(IP 매칭 전환 기준 4~5월 412명 수준)
샘플 안에는 대략 20명 정도만 남는다 — 이대로면 분류기 학습이 사실상 불가능하다. 시드 유저만
전수 조회한 04/05를 임베딩으로 바꿔서 pool에 강제 병합한다(음성은 5% 유지, 양성은 전수 포함).

```
.venv\Scripts\python.exe -m inference.user_profile   --input data/raw/04_seed_profile_apr_may.csv     --model-dir data/models/user_profile_202604_05        --output data/embeddings/seed_profile.csv
.venv\Scripts\python.exe -m inference.media_sequence --input data/raw/05_seed_media_apr_may.csv        --model-dir data/models/media_sequence_202604_05      --output data/embeddings/seed_media.csv

.venv\Scripts\python.exe -m scoring.build_stratified_pool \
  --sampled-emb data/embeddings/pool_profile.csv --full-emb data/embeddings/seed_profile.csv \
  --output data/embeddings/pool_profile_stratified.csv
.venv\Scripts\python.exe -m scoring.build_stratified_pool \
  --sampled-emb data/embeddings/pool_media.csv --full-emb data/embeddings/seed_media.csv \
  --output data/embeddings/pool_media_stratified.csv
```

양성이 충분하면(예: 원래 T2+ 기준처럼 pool 안에 수만 명대) 이 단계를 건너뛰고 2-4에서
`pool_profile.csv`/`pool_media.csv`를 그대로 써도 된다.

### 2-4. 스코어링 (지도학습 분류기)

train(분류기 학습, 아티팩트 저장) / inference(저장된 분류기로 재학습 없이 스코어링)로 나뉜다
— `embedding/` 모델들의 train→inference 구조와 동일. 극단적 클래스 불균형(양성 0.01~0.17%
수준) 대응으로 층화 미니배치 샘플링(`--pos-frac`)·라벨 층화 train/val 분할·PR-AUC/top-K%
recall 리포트가 들어있다(`scoring/train_supervised_lookalike.py` 상단 주석 참고).

```
.venv\Scripts\python.exe -m scoring.train_supervised_lookalike \
  --pool-profile-emb data/embeddings/pool_profile_stratified.csv \
  --pool-media-emb data/embeddings/pool_media_stratified.csv \
  --seed-ids data/raw/03_seed_users_apr_may.csv \
  --model-out data/models/fusion_classifier \
  --pos-frac 0.1 --topk-pct 0.1

.venv\Scripts\python.exe -m scoring.infer_supervised_lookalike \
  --model-dir data/models/fusion_classifier \
  --target-profile-emb data/embeddings/scoring_target_profile_jun.csv \
  --target-media-emb data/embeddings/scoring_target_media_jun.csv \
  --output data/embeddings/scored_jun.csv
```

학습 로그의 `val_recall@top10%`(검증셋 양성 중 상위 10% 안에 몇 %가 들어오는지)를 보고
epoch/`--pos-frac`을 조정한다 — 표본이 작을 땐 `val_auc`만으로는 판단하기 어렵다.

새 기간 스코어링 대상을 다시 스코어링만 할 땐(분류기 재학습 불필요) 두 번째 커맨드만
`--target-*`/`--output`을 바꿔 반복하면 된다.

옵션을 CLI 대신 JSON으로 관리하려면 `--config config/<이름>.json`을 쓴다
(`config/train_supervised_lookalike.example.json`, `config/infer_supervised_lookalike.example.json`
참고. 개별 CLI 옵션을 같이 주면 그 값이 config보다 우선).

**성능(2026-07-09 재학습, docs/_archive/202607091610.md)**: val_auc 0.79~0.82, 6월 postback
유저 269,914명 백테스트 상위 10% lift **1.60×**.

### 2-5. 백테스트 (전체 postback 유저 전환율 vs 스코어 상위 K% 전환율)

```
.venv\Scripts\python.exe -m evaluation.backtest \
  --scored data/embeddings/scored_jun.csv --score-col lookalike_score --scored-id-col req_user_id \
  --labels data/raw/06_backtest_labels_jun.csv --label-col conv_matched_ip_any_cmp_any_window --label-id-col ifa --label-threshold 1 \
  --id-map data/raw/07_scoring_target_profile_jun.csv --map-from-col req_user_id --map-to-col device_ifa \
  --output data/embeddings/backtest_jun.csv \
  --cumulative-output data/embeddings/backtest_jun_topk.csv
```

`06_backtest_labels_jun.sql`은 `label_col` 후보를 여러 개 뽑아둔다
(`conv_matched_ip_cmp_any_window`는 cmp_no까지 요구해 정밀도는 높지만 양성이 30명뿐이라
백테스트엔 표본이 부족함 — `conv_matched_ip_any_cmp_any_window`(IP만, 170명)를 기본으로 쓴다).

`--cumulative-output`은 "상위 10%/20%/.../100%를 타겟팅했다면"에 바로 대응하는 누적
lift 표(`evaluation.backtest.cumulative_topk_summary`)를 만든다. 옵션을 CLI 대신 JSON으로
관리하려면 `--config config/<이름>.json`을 쓴다(`config/backtest.example.json` 참고).

**주의(학습-검증 겹침/leakage)**: 07/08(6월 postback 유저 전체)은 4~5월 pool/시드와 겹치는
유저를 배제하지 않는다 — 시드(양성 485명) 중 일부가 6월에도 postback을 내면 백테스트
모집단에 다시 나타날 수 있고, 그 사람은 분류기가 "예측"한 게 아니라 이미 정답으로 학습한
사람이라 lift 수치가 실제보다 낙관적으로 나올 수 있다. 그래서 백테스트는 "모델이 방향은
맞게 가는지" 확인하는 용도로만 쓰고, 실제 후보 리스트는 정의상 pool/시드와 안 겹치는
2-6(신규 유저)으로 뽑는다.

### 2-6. 신규 유저 스코어링 (실제 후보 리스트 산출, leakage 없음)

백테스트(2-5)는 이미 반응한 유저로 모델을 검증하는 단계였다면, 이건 실제로 아직 반응 안 한
유저 중 전환 가능성이 높은 사람을 찾아내는 단계 — 원래 이 프로젝트의 목표였던 "신규 유저
룩어라이크 타겟팅"을 새 모델(IP 매칭 전환 기준)로 다시 수행한다. 재학습 없이 2-4에서 이미
학습된 분류기를 그대로 쓴다.

```
# 1) querys/pipeline/09,10.sql을 Athena에서 실행, 결과 CSV를 data/raw/에 저장
#    (4~5월 bid log에 없다가 6월에 처음 등장한 신규 유저 전원 — 샘플링 없음)

# 2) 임베딩 추출 (기존 학습된 임베딩 모델 재사용, 재학습 없음)
.venv\Scripts\python.exe -m inference.user_profile   --input data/raw/09_new_users_profile_jun.csv --model-dir data/models/user_profile_202604_05   --output data/embeddings/new_users_profile_jun.csv
.venv\Scripts\python.exe -m inference.media_sequence --input data/raw/10_new_users_media_jun.csv    --model-dir data/models/media_sequence_202604_05 --output data/embeddings/new_users_media_jun.csv

# 3) 스코어링 (기존 fusion_classifier 재사용, 재학습 없음)
.venv\Scripts\python.exe -m scoring.infer_supervised_lookalike \
  --model-dir data/models/fusion_classifier \
  --target-profile-emb data/embeddings/new_users_profile_jun.csv \
  --target-media-emb data/embeddings/new_users_media_jun.csv \
  --output data/embeddings/new_users_scored_jun.csv
```

`new_users_scored_jun.csv`(`req_user_id`, `lookalike_score`)가 실제 타겟팅에 쓸 수 있는
산출물이다 — 점수 상위 유저부터 우선순위를 매기면 된다. 이 유저들은 정의상(4~5월 bid log에
아예 없었음) 학습 pool/시드와 겹치지 않으므로, 2-5의 leakage 우려가 여기엔 해당하지 않는다.

**threshold 정하는 법**: 이 신규 유저 모집단엔 정답 라벨이 없어서(아직 전환 안 한 사람들
이라 당연함) 직접 정밀도를 잴 수 없다 — 대신 같은 분류기·같은 점수 체계로 검증된 2-5
백테스트의 decile 경계값(`evaluation.backtest` 출력의 `score_min`)을 그대로 점수 컷오프로
쓴다. 2026-07-09 기준 검증된 컷오프:

| 컷오프(score ≥) | 백테스트 기준 lift | 신규 유저 229,724명 중 해당 인원 |
|---|---|---|
| 0.72 | 1.60×(상위 10%) | 13,996명 (6.1%) |
| 0.41 | 1.44×(상위 20%) | 32,054명 (14.0%) |
| 0.17 | 1.22×(상위 30%) | 52,332명 (22.8%) |

예산이 빠듯하면 0.72(고정밀 1.4만 명), 넓게 훑고 싶으면 0.41(3.2만 명)을 권장한다 —
0.17 밑으로는 lift가 계속 떨어지는 추세라(2-5 누적 표 참고) 그 아래로 확장하는 건 권장하지
않는다. 신규 유저 모집단의 점수 분포 자체는 postback 유저보다 훨씬 낮게 쏠려 있다(중앙값
0.002) — 정상이다, 아직 아무 반응도 안 한 유저들이라 전체적으로 낮게 나오는 게 맞다.

## 산출물 현황 요약

| 산출물 | 위치 | 상태 |
|---|---|---|
| user_profile 임베딩 모델 | `data/models/user_profile_202604_05/` | 4~5월 59만 유저(5% 샘플), 30 epoch |
| media_sequence 임베딩 모델 | `data/models/media_sequence_202604_05/` | 4~5월 10만 유저(로컬 추가 샘플, 파일럿용), 5 epoch — 프로덕션 전환 시 전체/30epoch 재학습 권장 |
| 지도학습 fusion 분류기 | `data/models/fusion_classifier/` | IP+cmp_no 매칭 전환 시드, 층화 pool 425,043명(양성 388명), 20 epoch |
| 6월 postback 유저 스코어 | `data/embeddings/scored_jun.csv` | 269,914명 |
| 백테스트 결과 | `data/embeddings/backtest_jun.csv` / `backtest_jun_topk.csv` | 상위 10% lift 1.60× |

## 알려진 이슈 / 주의사항

- **`addi_bid_log_flatten`은 앱(CTV/Android TV) 전용 인벤토리** — `site_page`/`site_content_genre`/
  `site_content_language`/`device_connectiontype`/`device_pxratio` 컬럼이 없음(형제 테이블
  `abi_bid_log_flatten`에는 있음). 컬럼 존재 여부는 항상 실제 데이터로 먼저 확인할 것.
- **`media`는 `app_bundle`이 아니라 `content_genre` 대표값** — addi는 CTV라 app_bundle이
  통신사 IPTV 앱 3종뿐이라 사실상 상수(다음-아이템 예측이 무의미해짐, loss가 0에서 안 움직임).
  `content_genre`(115종)로 바꿔서 실제로 학습되는 모델이 됨. `querys/pipeline/01,02.sql`에
  이미 반영됨.
- **`adspid`(광고 마스터 PK)와 `cmp_no`(로그 테이블 캠페인 ID)는 매핑이 없음** — 전수 조사로
  확인됨. 그래서 `addi_business`(광고주 정보)는 유저/캠페인 어느 쪽에도 못 붙임 — 광고주 속성
  기반 two-tower 모델은 현재 데이터로 불가능. 반면 `raw_conv_web(_imp).cmp_no`는 addi
  cmp_no와 같은 ID 체계임을 확인(`docs/_archive/202607091533.md`).
- **컴플라이언스 필터 필수**: `req_ext_allow_user_data_collection = '1'`만 포함(NULL/미채움 제외),
  `device_lmt = '1'`(옵트아웃) 제외. 모든 오디언스 쿼리에 이미 적용됨.
- **Athena/Glue 타입 주의**: 숫자처럼 보이는 컬럼이 실제로는 `bigint`/`double`로 추론된 경우가
  많음 — 문자열 함수 쓰기 전엔 `CAST(col AS VARCHAR)`로 감쌀 것.
- **극단적 클래스 불균형**: IP 매칭 전환 기준 양성 비율이 0.01~0.17% 수준으로 매우 낮다 —
  `scoring.train_supervised_lookalike`의 `--pos-frac`/층화 train-val 분할이 이를 완화하지만,
  `val_recall@top10%`가 epoch마다 크게 흔들릴 수 있다(검증셋 양성 자체가 수십 명 수준이라).
