# addi_data_embedding

특정 광고(`cmp_no`)에 관심 있는 사용자 리스트를 뽑고(규칙 기반), 아직 postback(전환)이 없는
신규 유저 중 과거 관심 유저와 행동이 비슷한 유저를 임베딩으로 찾아내는(ML 기반) 프로젝트.
원래 SQL/문서 저장소(`addi_data_embedding`)와 임베딩 모델 코드 저장소(`user-to-ad-encoder`)가
분리돼 있었는데, 이 저장소 하나로 합쳤다(2026-07-08).

## 폴더 구조

```
querys/       Athena SQL — 이 환경엔 Athena 접근 권한이 없어 콘솔에서 직접 실행 필요 (아래 §1)
embedding/    모델 구조/데이터셋/전처리 정의 (user_profile, media_sequence) — train/inference가 공유
train/        학습 실행 진입점 (아티팩트 저장까지만, 임베딩은 안 뽑음)
inference/    학습된 모델로 재학습 없이 임베딩 추출
scoring/      fusion + lookalike 스코어링 (지도학습 분류기, train·infer 분리)
evaluation/   임베딩 거리 확인(distance.py), 스코어 대비 실제 결과 백테스트(backtest.py)
pipeline/     학습→추론→스코어링(→백테스트)을 config 하나로 한번에 실행 (아래 §2-0)
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

`querys/audience_embedding/01~06.sql`을 Athena 콘솔에서 순서대로 실행하고, 결과 CSV를 아래
이름으로 `data/raw/`에 저장한다.

| # | SQL | 저장 파일명 | 그레인 |
|---|---|---|---|
| 01 | `01_top500_media_visit.sql` | `01_top500_media_visit.csv` | 이벤트 (유저×콘텐츠장르×시각), 학습용, 4~5월 |
| 02 | `02_user_profile.sql` | `02_user_profile.csv` | 유저 1행, 학습용, 4~5월 |
| 03 | `03_seed_interested_users_apr_may.sql` | `03_seed_interested_users_apr_may.csv` | 시드(4~5월 관심 유저) 목록 |
| 04 | `04_new_users_top500_media_visit_jun.sql` | `04_new_users_top500_media_visit_jun.csv` | 6월 신규 유저 이벤트 (스코어링 대상) |
| 05 | `05_new_users_user_profile_jun.sql` | `05_new_users_user_profile_jun.csv` | 6월 신규 유저 프로필 (req_user_id↔device_ifa 매핑 포함) |
| 06 | `06_postback_jun_for_backtest.sql` | `06_postback_max_tier_jun.csv` | 6월 device_ifa별 최고 도달 tier (백테스트용) |

각 CSV의 컬럼/결측률/분포는 [`docs/audience_embedding_data_schema.md`](docs/audience_embedding_data_schema.md) 참고.

**주의**: 현재 01/02/04/05는 데이터량이 너무 커서(캠페인 무필터 2개월치, 7일 8,990만 건
기준 환산 시 7~8억 건대) 유저 단위 5% 샘플링이 걸려 있다(`mod(crc32(...), 100) < 5`, 각 SQL
파일 주석 참고). **실제 서비스용 후보 리스트를 뽑을 땐 이 조건을 지우고 재실행**해야 한다
(모델 재학습은 유지해도 됨 — 학습은 표본이어도 스코어링 대상은 전수여야 함).

`querys/athena_validation_queries/`(데이터 정합성 검증)는 별도 트랙, 이 파이프라인 실행에는
필요 없다.

## 2. 파이프라인 실행 (학습 → 추론 → 스코어링 → 백테스트)

### 2-0. 한번에 실행 (권장)

`querys/audience_embedding/01~05.sql` 결과 CSV를 `data/raw/`에 올려둔 상태라면(06은 아래
2-4처럼 백테스트를 켤 때만 필요), 학습→추론→스코어링(→백테스트)을 한 커맨드로 실행한다.
개별 단계 함수를 그대로 호출할 뿐이라 산출물 위치는 아래 2-1~2-4의 수동 실행과 동일하다.

```
cp config/pipeline.example.json config/pipeline.json   # 값 채우기 (경로는 기본값 그대로 써도 됨)
.venv\Scripts\python.exe -m pipeline.run_all --config config/pipeline.json
```

`config/pipeline.example.json` 참고. `backtest.enabled`를 `true`로 켜면 4단계까지, 기본(`false`)이면
스코어링까지만 실행한다(실제 postback이 쌓인 기간에만 백테스트가 의미 있음 — 2-4 참고).

새 기간 신규 유저만 다시 추론→스코어링하고 싶을 때(임베딩 모델 재학습 불필요, 2-1 참고)는
`--skip-train`을 붙인다:

```
.venv\Scripts\python.exe -m pipeline.run_all --config config/pipeline.json --skip-train
```

아래 2-1~2-4는 이 파이프라인이 내부적으로 호출하는 개별 단계 — 한 단계만 다시 돌리거나
디버깅할 때 직접 쓴다.

### 2-1. 학습 (최초 1회, 이후 새 기간 데이터가 쌓이면 재실행)

```
.venv\Scripts\python.exe -m train.user_profile   --input data/raw/02_user_profile.csv      --output data/models/user_profile_addi
.venv\Scripts\python.exe -m train.media_sequence --input data/raw/01_top500_media_visit.csv --output data/models/media_sequence_addi_genre
```

GPU가 있는 환경에서는 `--device auto`(기본값, cuda 있으면 자동 사용)/`--device cuda`/`--device cpu`로
지정한다(`--config`로 주는 JSON에도 `"device"` 키로 넣을 수 있음).

모델 구조/필드별 처리 방식은 [`docs/model_architecture.md`](docs/model_architecture.md) 참고.

### 2-2. 추론 (pool=4~5월 전체, target=6월 신규 유저 — 새 데이터가 생기면 매번 반복)

```
.venv\Scripts\python.exe -m inference.user_profile   --input data/raw/02_user_profile.csv                    --model-dir data/models/user_profile_addi        --output data/embeddings/user_profile_apr_may.csv
.venv\Scripts\python.exe -m inference.media_sequence --input data/raw/01_top500_media_visit.csv               --model-dir data/models/media_sequence_addi_genre --output data/embeddings/media_sequence_apr_may.csv
.venv\Scripts\python.exe -m inference.user_profile   --input data/raw/05_new_users_user_profile_jun.csv           --model-dir data/models/user_profile_addi        --output data/embeddings/user_profile_jun_new.csv
.venv\Scripts\python.exe -m inference.media_sequence --input data/raw/04_new_users_top500_media_visit_jun.csv     --model-dir data/models/media_sequence_addi_genre --output data/embeddings/media_sequence_jun_new.csv
```

### 2-3. 스코어링 (지도학습 분류기)

train(분류기 학습, 아티팩트 저장) / inference(저장된 분류기로 재학습 없이 스코어링)로 나뉜다
— `embedding/` 모델들의 train→inference 구조와 동일. (centroid 코사인 유사도 baseline은
백테스트에서 상위 90% 구간의 순위를 전혀 못 갈라 폐기 — 히스토리는 `docs/_archive/` 참고.)

```
.venv\Scripts\python.exe -m scoring.train_supervised_lookalike \
  --pool-profile-emb data/embeddings/user_profile_apr_may.csv \
  --pool-media-emb data/embeddings/media_sequence_apr_may.csv \
  --seed-ids data/raw/03_seed_interested_users_apr_may.csv \
  --model-out data/models/fusion_classifier_addi

.venv\Scripts\python.exe -m scoring.infer_supervised_lookalike \
  --model-dir data/models/fusion_classifier_addi \
  --target-profile-emb data/embeddings/user_profile_jun_new.csv \
  --target-media-emb data/embeddings/media_sequence_jun_new.csv \
  --output data/embeddings/supervised_lookalike_scored_jun.csv
```

새 기간 신규 유저를 스코어링만 다시 할 땐(분류기 재학습 불필요) 두 번째 커맨드만
`--target-*`/`--output`을 바꿔 반복하면 된다.

옵션을 CLI 대신 JSON으로 관리하려면 `--config config/<이름>.json`을 쓴다
(`config/train_supervised_lookalike.example.json`, `config/infer_supervised_lookalike.example.json`
참고. 개별 CLI 옵션을 같이 주면 그 값이 config보다 우선).

**성능(2026-07-07 파일럿, 6월 신규 유저 25,449명 기준)**: AUC 0.61, 최상위 10% lift **2.07x**
(postback 라벨로 얕은 분류기(128→64→1) 추가 학습 필요).

### 2-4. 백테스트 (실제 postback이 쌓인 기간에만 가능)

```
.venv\Scripts\python.exe -m evaluation.backtest \
  --scored data/embeddings/supervised_lookalike_scored_jun.csv --score-col lookalike_score --scored-id-col req_user_id \
  --labels data/raw/06_postback_max_tier_jun.csv --label-col max_tier --label-id-col ifa --label-threshold 1 \
  --id-map data/raw/05_new_users_user_profile_jun.csv --map-from-col req_user_id --map-to-col device_ifa \
  --output data/embeddings/supervised_lookalike_scored_jun_backtest.csv
```

`--label-threshold`: 1=T2(참여시작) 이상, 4=T3 이상, 6=T4(완료)만 — 몇 tier 이상을 "전환"으로
볼지 조정.

옵션을 CLI 대신 JSON으로 관리하려면 `--config config/<이름>.json`을 쓴다
(`config/backtest.example.json` 참고. 개별 CLI 옵션을 같이 주면 그 값이 config보다 우선).

### 2-5. 전환 정의 변경 백테스트 (postback 유저 IP 매칭, 실험 단계)

기존 백테스트(2-4)는 "postback tier(T2+) 도달 여부"를 전환으로 본다. 여기서는 관점을 바꿔
"postback 유저 중 실제 광고주 몰(`"prod_addi_conv".raw_conv_web`/`raw_conv_web_imp`) IP와
매칭되는 유저 비율"을 전환으로 본다 — 자세한 배경/스키마 조사 과정은
[`querys/addi_conv/README.md`](querys/addi_conv/README.md), 실험 결과 전체는
[`docs/_archive/202607091533.md`](docs/_archive/202607091533.md) 참고.

**아직 재학습 전 단계**: 기존(T2+ 시드로 학습된) 모델을 그대로 써서 새 라벨로 백테스트만
해본 결과다. 신호는 있으나 약함(상위 10~30% lift 1.2~1.3배 수준) — 재학습하면 개선 여지가
있다는 게 다음 단계(§2-3 재학습을 이 라벨로 다시 실행)의 동기다.

```
# 1) querys/addi_conv/09~11.sql을 Athena에서 실행, 결과 CSV를 data/raw/에 저장
#    (09: 6월 postback 유저 IP 매칭 라벨, 10/11: 6월 postback 유저 전원의 프로필/미디어 방문)

# 2) 임베딩 추출 (기존 모델 재사용, 재학습 없음)
.venv\Scripts\python.exe -m inference.user_profile   --input data/raw/10_postback_users_profile_jun.csv      --model-dir data/models/user_profile_addi_202604_05        --output data/embeddings/user_profile_postback_jun.csv
.venv\Scripts\python.exe -m inference.media_sequence --input data/raw/11_postback_users_media_visit_jun.csv  --model-dir data/models/media_sequence_addi_genre_202604_05 --output data/embeddings/media_sequence_postback_jun.csv

# 3) 스코어링 (기존 fusion_classifier_addi 재사용)
.venv\Scripts\python.exe -m scoring.infer_supervised_lookalike \
  --model-dir data/models/fusion_classifier_addi \
  --target-profile-emb data/embeddings/user_profile_postback_jun.csv \
  --target-media-emb data/embeddings/media_sequence_postback_jun.csv \
  --output data/embeddings/supervised_lookalike_scored_postback_jun.csv

# 4) 백테스트 (라벨 = IP 매칭 여부)
.venv\Scripts\python.exe -m evaluation.backtest \
  --scored data/embeddings/supervised_lookalike_scored_postback_jun.csv --score-col lookalike_score --scored-id-col req_user_id \
  --labels data/raw/09_postback_conv_match_jun_for_backtest.csv --label-col conv_matched_ip_any_cmp_any_window --label-id-col ifa --label-threshold 1 \
  --id-map data/raw/10_postback_users_profile_jun.csv --map-from-col req_user_id --map-to-col device_ifa \
  --output data/embeddings/postback_jun_backtest.csv \
  --cumulative-output data/embeddings/postback_jun_backtest_topk.csv
```

`09_postback_conv_match_jun_for_backtest.sql`은 `label_col` 후보를 여러 개 뽑아둔다
(`conv_matched_ip_cmp_any_window`는 cmp_no까지 요구해 정밀도는 높지만 양성이 30명뿐이라
백테스트엔 표본이 부족함 — `conv_matched_ip_any_cmp_any_window`(IP만, 170명)를 기본으로 쓴다).

### 2-6. 재학습 (IP 매칭 전환 라벨로, 극단적 불균형 대응 포함)

2-5의 1차 백테스트로 "재학습할 가치가 있다"는 최소 신호를 확인한 뒤의 단계. 두 가지 문제를
먼저 풀어야 한다(배경은 [`docs/_archive/202607091533.md`](docs/_archive/202607091533.md) "다음
단계" 참고):

1. **학습 pool의 5% 샘플링 문제** — 양성(IP+cmp_no 매칭, 4~5월 기준 412명)이 5% 샘플 안에는
   대략 20명 정도만 남는다. 매칭 유저만 전수로 별도 조회해서 pool에 강제 병합한다
   (`scoring.build_stratified_pool`).
2. **극단적 불균형(양성 0.01~0.17%)** — `scoring.train_supervised_lookalike`에 층화
   미니배치 샘플링(`--pos-frac`)과 라벨 층화 train/val 분할, PR-AUC·top-K% recall 리포트를
   추가했다(코드 변경, 시드 자체는 그대로 넣으면 자동 적용됨).

```
# 1) querys/addi_conv/12~14.sql을 Athena에서 실행, 결과 CSV를 data/raw/에 저장
#    (12: 4~5월 IP+cmp_no 매칭 유저 목록=새 시드 후보, 13/14: 그 유저들의 프로필/미디어 방문 전수 조회)

# 2) 매칭 유저만 임베딩 추출 (기존 학습된 임베딩 모델 재사용, 재학습 아님)
.venv\Scripts\python.exe -m inference.user_profile   --input data/raw/13_conv_matched_users_profile_apr_may.csv     --model-dir data/models/user_profile_addi_202604_05        --output data/embeddings/user_profile_conv_matched_apr_may.csv
.venv\Scripts\python.exe -m inference.media_sequence --input data/raw/14_conv_matched_users_media_visit_apr_may.csv --model-dir data/models/media_sequence_addi_genre_202604_05 --output data/embeddings/media_sequence_conv_matched_apr_may.csv

# 3) 기존 5% 샘플 pool에 병합 (음성은 5% 유지, 양성은 전수 포함)
.venv\Scripts\python.exe -m scoring.build_stratified_pool \
  --sampled-emb data/embeddings/user_profile_apr_may.csv \
  --full-emb data/embeddings/user_profile_conv_matched_apr_may.csv \
  --output data/embeddings/user_profile_apr_may_stratified.csv
.venv\Scripts\python.exe -m scoring.build_stratified_pool \
  --sampled-emb data/embeddings/media_sequence_apr_may.csv \
  --full-emb data/embeddings/media_sequence_conv_matched_apr_may.csv \
  --output data/embeddings/media_sequence_apr_may_stratified.csv

# 4) 분류기 재학습 (시드 = 12번 쿼리 결과, pool = 3번에서 병합한 층화 pool)
.venv\Scripts\python.exe -m scoring.train_supervised_lookalike \
  --pool-profile-emb data/embeddings/user_profile_apr_may_stratified.csv \
  --pool-media-emb data/embeddings/media_sequence_apr_may_stratified.csv \
  --seed-ids data/raw/12_conv_matched_users_apr_may.csv \
  --model-out data/models/fusion_classifier_addi_conv_ip \
  --pos-frac 0.1 --topk-pct 0.1
```

학습 로그의 `val_recall@top10%`(상위 10% 안에 검증셋 양성 중 몇 %가 들어오는지)를 보고
epoch/`--pos-frac`을 조정한다 — 표본이 워낙 작아 `val_auc`만으로는 판단하기 어렵다. 재학습한
모델로 §2-5의 4번 스코어링·백테스트 커맨드를 다시 돌려서(`--model-dir`을
`fusion_classifier_addi_conv_ip`로 교체) `docs/_archive/202607091533.md`의 1차 결과와
비교한다.

## 산출물 현황 요약

| 산출물 | 위치 | 상태 |
|---|---|---|
| user_profile 임베딩 모델 | `data/models/user_profile_addi/` | 4~5월 59만 유저(5% 샘플), 30 epoch |
| media_sequence 임베딩 모델 | `data/models/media_sequence_addi_genre/` | 4~5월 10만 유저(로컬 추가 샘플, 파일럿용), 5 epoch — 프로덕션 전환 시 전체/30epoch 재학습 권장 |
| 지도학습 fusion 분류기 | `data/models/fusion_classifier_addi/` | 시드 라벨 기반, 20 epoch |
| 6월 신규 유저 스코어 | `data/embeddings/supervised_lookalike_scored_jun.csv` | 25,449명 |

## 알려진 이슈 / 주의사항

- **`addi_bid_log_flatten`은 앱(CTV/Android TV) 전용 인벤토리** — `site_page`/`site_content_genre`/
  `site_content_language`/`device_connectiontype`/`device_pxratio` 컬럼이 없음(형제 테이블
  `abi_bid_log_flatten`에는 있음). 컬럼 존재 여부는 항상 실제 데이터로 먼저 확인할 것.
- **`media`는 `app_bundle`이 아니라 `content_genre` 대표값** — addi는 CTV라 app_bundle이
  통신사 IPTV 앱 3종뿐이라 사실상 상수(다음-아이템 예측이 무의미해짐, loss가 0에서 안 움직임).
  `content_genre`(115종)로 바꿔서 실제로 학습되는 모델이 됨. `querys/audience_embedding/01,04.sql`에
  이미 반영됨.
- **`adspid`(광고 마스터 PK)와 `cmp_no`(로그 테이블 캠페인 ID)는 매핑이 없음** — 전수 조사로
  확인됨. 그래서 `addi_business`(광고주 정보)는 유저/캠페인 어느 쪽에도 못 붙임 — 광고주 속성
  기반 two-tower 모델은 현재 데이터로 불가능.
- **컴플라이언스 필터 필수**: `req_ext_allow_user_data_collection = '1'`만 포함(NULL/미채움 제외),
  `device_lmt = '1'`(옵트아웃) 제외. 모든 오디언스 쿼리에 이미 적용됨.
- **Athena/Glue 타입 주의**: 숫자처럼 보이는 컬럼이 실제로는 `bigint`/`double`로 추론된 경우가
  많음 — 문자열 함수 쓰기 전엔 `CAST(col AS VARCHAR)`로 감쌀 것.
