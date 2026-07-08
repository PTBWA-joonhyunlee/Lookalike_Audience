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

**주의**: 현재 01/02/04/05는 데이터량이 너무 커서(캠페인 무필터 2개월치, 7일 8,990만 건
기준 환산 시 7~8억 건대) 유저 단위 5% 샘플링이 걸려 있다(`mod(crc32(...), 100) < 5`, 각 SQL
파일 주석 참고). **실제 서비스용 후보 리스트를 뽑을 땐 이 조건을 지우고 재실행**해야 한다
(모델 재학습은 유지해도 됨 — 학습은 표본이어도 스코어링 대상은 전수여야 함).

`querys/audience_list_extraction/`(J1/J2, 규칙 기반 T1~T4 티어)와
`querys/athena_validation_queries/`(데이터 정합성 검증)는 별도 트랙 — §6 참고.

## 2. 학습 (최초 1회, 이후 새 기간 데이터가 쌓이면 재실행)

```
.venv\Scripts\python.exe -m train.user_profile   --input data/raw/02_user_profile.csv      --output data/models/user_profile_addi
.venv\Scripts\python.exe -m train.media_sequence --input data/raw/01_top500_media_visit.csv --output data/models/media_sequence_addi_genre
```

GPU가 있는 환경에서는 `--device auto`(기본값, cuda 있으면 자동 사용)/`--device cuda`/`--device cpu`로
지정한다(`--config`로 주는 JSON에도 `"device"` 키로 넣을 수 있음).

모델 구조/필드별 처리 방식은 [`docs/model_architecture.md`](docs/model_architecture.md) 참고.

## 3. 추론 (pool=4~5월 전체, target=6월 신규 유저 — 새 데이터가 생기면 매번 반복)

```
.venv\Scripts\python.exe -m inference.user_profile   --input data/raw/02_user_profile.csv                    --model-dir data/models/user_profile_addi        --output data/embeddings/user_profile_apr_may.csv
.venv\Scripts\python.exe -m inference.media_sequence --input data/raw/01_top500_media_visit.csv               --model-dir data/models/media_sequence_addi_genre --output data/embeddings/media_sequence_apr_may.csv
.venv\Scripts\python.exe -m inference.user_profile   --input data/raw/05_new_users_user_profile_jun.csv           --model-dir data/models/user_profile_addi        --output data/embeddings/user_profile_jun_new.csv
.venv\Scripts\python.exe -m inference.media_sequence --input data/raw/04_new_users_top500_media_visit_jun.csv     --model-dir data/models/media_sequence_addi_genre --output data/embeddings/media_sequence_jun_new.csv
```

## 4. 스코어링 (지도학습 분류기)

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

## 5. 백테스트 (실제 postback이 쌓인 기간에만 가능)

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

## 6. 규칙 기반 티어 추출 (J1/J2 — postback 있는 과거 캠페인 전용, 별도 트랙)

임베딩 없이 bid+postback 로그만으로 "이미 반응한 유저"를 T1(노출)~T4(완료) 티어로 뽑는
쿼리. `querys/audience_list_extraction/J1_audience_tier_full.sql`(전체 분포 확인용),
`J2_interested_users_final.sql`(T2 이상 최종 리스트) — 파일 상단 `cmp_no` 값만 바꿔서 재사용.
파일럿 산출물(`cmp_no=10115`): `data/audience_list_extraction/`.

## 산출물 현황 요약

| 산출물 | 위치 | 상태 |
|---|---|---|
| user_profile 임베딩 모델 | `data/models/user_profile_addi/` | 4~5월 59만 유저(5% 샘플), 30 epoch |
| media_sequence 임베딩 모델 | `data/models/media_sequence_addi_genre/` | 4~5월 10만 유저(로컬 추가 샘플, 파일럿용), 5 epoch — 프로덕션 전환 시 전체/30epoch 재학습 권장 |
| 지도학습 fusion 분류기 | `data/models/fusion_classifier_addi/` | 시드 라벨 기반, 20 epoch |
| 6월 신규 유저 스코어 | `data/embeddings/supervised_lookalike_scored_jun.csv` | 25,449명 |
| J1/J2 규칙 기반 리스트 | `data/audience_list_extraction/` | cmp_no=10115 파일럿 |

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
