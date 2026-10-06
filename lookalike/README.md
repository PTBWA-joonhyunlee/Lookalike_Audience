# lookalike/ — seed 기반 신규 유저 룩어라이크

외부 seed 리스트(광고 ID)를 두고 propfit 소스에서 비슷한 신규 유저를 찾는다. 이 폴더는 **독립 작업
루트**다 — 저장소 루트가 아니라 여기로 `cd` 한 뒤 실행한다. AWS 키/IAM 정책은 `../config/`.

## 시나리오 1 — 신규 seed (구현됨)

`data/seeds/<seed>/input/`에 seed CSV(첫 열 = 광고 ID, 헤더 유무 자동 판별)를 두고 한 번에 실행한다.
Athena 테이블을 영구 생성하지 않는다(임시 외부 테이블은 끝나면 DROP).

```
cd lookalike
..\.venv\Scripts\python.exe -m pipeline.run_seed_scenario1 --seed-name je --input-csv data/seed/je_sample_adid.csv ^
    --period 2026-06-01:2026-09-30 --top-pct 10        # --dry-run: 경로/단계별 상태만 확인
```

단계: 업로드+임시 테이블 -> id_space_check(direct/crosswalk 자동 판정, 애매하면 중단) -> seed segment
UNLOAD -> candidate segment UNLOAD(기간별 캐시 `data/candidates/<period_key>/`) -> 임베딩 -> 학습 ->
스코어링(기존 seed 전부 로컬에서 제외) -> top N%. 산출물이 있으면 건너뛰고 `--force`로 재실행.
결과: `data/seeds/<seed>/<run_id>/scores/candidate_scores_top<N>pct.csv`.

- pool: `data/pools/<pool_id>/pool_spec.json`(기본 `legacy` = 기존 pool, 2026-04~05). candidate 기간이
  pool 기간과 겹치면 거부한다. 오토인코더는 아직 `legacy`만 지원.

## 시나리오 1 변형 — Athena seed 테이블 + 멀티라벨 (구현됨)

seed가 이미 Athena 테이블이거나 seed가 여러 개일 때. 업로드/임시 테이블 없이 테이블을 직접 읽고, seed 하나당
sigmoid 헤드 하나인 멀티라벨 분류기(공유 trunk, 라벨별 `pos_weight`, 라벨 조합별 층화 분할)를 한 번에 학습한다.
한 유저가 여러 seed에 동시에 속할 수 있고 pool은 모든 라벨이 0이다. seed 간 포함 관계가 크면(한 seed가 다른
seed의 부분집합이면) 두 점수가 비슷해져 교집합이 구조적으로 높게 나온다.

```
cd lookalike
..\.venv\Scripts\python.exe -u -m pipeline.run_seed_table_multilabel --group sepo_ctv ^
    --seed sepo_17177=dev-ptbwa-da.sepo_17177:adid --seed sepo_17179=dev-ptbwa-da.sepo_17179:adid ^
    --ae-version ae_2024-09_2026-09_s30 --period 2026-03-01:2026-09-30 --allow-overlap ^
    --target-union 1500000 --report-pcts 2,4,6,8,10 --run-id r1 --output-table sepo_lal_150
#   --dry-run: 경로/상태만   --publish-only --output-table T: 추출은 건너뛰고 기존 결과로 테이블만 생성
```

| 옵션 | 의미 |
|---|---|
| `--seed 라벨=DB.테이블:컬럼` | Athena seed 테이블(반복 가능). UUID 형식 필터는 걸지 않고 매칭은 id_space_check가 판정 |
| `--id-mode` | 자동 판정이 애매할 때 지정: `direct` / `crosswalk:uuid` / `crosswalk:platform_ad_id` |
| `--target-union N` | 모든 seed에 같은 상위 pct를 주되 합집합이 N에 가장 가까운 pct를 이분 탐색(없으면 `--top-pct`) |
| `--at-least` | `--target-union`과 함께: 가장 가까운 값 대신 합집합이 N **이상**이 되는 최소 pct를 고른다 |
| `--report-pcts` | 이 pct들마다 seed 쌍별 교집합 표 생성(교집합 / seed 인원, 기본 2,4,6,8,10) |
| `--output-table T` | 끝에서 `union_top.csv`를 `s3://.../delivery/<group>/<run_id>/T/`에 올리고 `dev-ptbwa-da.T` 외부 테이블 생성 |

- 산출물 `data/seeds/<group>/<run_id>/`: `seed_segments/<라벨>.csv`, `id_space_check_<라벨>.json`, `model/model_multilabel.pt`,
  `scores/{candidate_scores.csv, union_top.csv, top_<라벨>.csv, overlap_by_pct.csv}`. 테이블 컬럼:
  `device_ifa, score_<라벨>…, in_<라벨>…`.
- `--output-table`은 같은 이름의 테이블이 있으면 덮어쓰지 않고 중단하며, 생성 후 행 수를 파일과 대조한다.
  IAM에 `glue:CreateTable`(dev-ptbwa-da)이 필요하다(`config/iam/`).
- **같은 run-id의 실행기를 동시에 두 개 띄우지 않는다**(Athena 쿼리 중복, 후보 CSV 행 2배, 임베딩 파일 충돌 — 루트 `CLAUDE.md` 규칙).

## 시나리오 2 — pool 추출 + 오토인코더 재학습 (구현됨)

pool 조건(추출 기간, 표본 비율, region, OS)을 지정하면 pool segment를 Athena에서 추출(UNLOAD)하고
오토인코더를 학습한다. 오토인코더 버전 하나 = `data/autoencoders/<ae_version>/` 디렉터리 하나.

```
cd lookalike
..\.venv\Scripts\python.exe -m pipeline.run_ae_scenario2 --pool-id pool_2026-04_05_s5 ^
    --period 2026-04-01:2026-05-31 --sample-pct 5 --epochs 30
#   --explain-only: Athena EXPLAIN으로 쿼리만 검증(스캔 비용 없음)   --dry-run: 경로/상태만 출력
```

| 옵션 | 의미 |
|---|---|
| `--period` | pool 추출 기간(bid log 활동 기준, 반복 가능, 시작은 월 1일·같은 연도) |
| `--sample-pct` / `--sample-salt` | device_ifa crc32 해시 표본 비율(%, 0.01% 단위, 기본 5) / 다른 salt = 다른 표본 |
| `--region` / `--any-os` | device_geo_region 접두사(기본 KR) / Android 필터 해제 |
| `--ae-version` | 저장 이름(기본 `ae_<pool_id>_<날짜>`) |
| `--epochs --batch-size --lr --hidden-dim --age-embed-dim --val-split --patience --seed` | 학습 설정(z 차원은 32 고정) |

- 같은 `--pool-id`에 다른 조건을 주면 거부한다(pool은 불변, 새 이름을 쓸 것).
- 산출물: `data/pools/<pool_id>/{pool_spec.json, pool_segment.csv, emb_<ae_version>.csv}`,
  `data/autoencoders/<ae_version>/{model.pt, age_bracket_vocab.json, segment_bert_lookup.npz, config.json}`.
  모델은 val 재구성 손실이 가장 낮은 에폭의 가중치다.
- `config.json`: 모델 구조 + 학습 설정 + 에폭별 손실(history) + 학습 pool 조건 + git commit + model.pt 해시.

시나리오 1에서 만든 오토인코더를 쓰려면 `--ae-version <이름>`을 준다(기본 `legacy` = 시나리오 2 이전 모델).
`--pool-id`를 생략하면 그 오토인코더를 학습한 pool을 쓴다.

## 어떤 임베딩 모델을 썼는지 기록

시나리오 1의 모든 산출물이 오토인코더에 묶여 있다 — `data/seeds/<seed>/<run_id>/`:
`ae_binding.json`(ae_version + model.pt 해시, 다른 오토인코더로 같은 run을 이어 실행하면 거부),
`model/config.json`(`autoencoder` 블록 + `classifier_train` 학습 설정/결과), `run.json`(`autoencoder`).
후보 임베딩 캐시도 `candidates/<period_key>/emb_<ae_version>.csv`로 버전별이다.

## 경로 규칙 (`pipeline/paths.py`)

로컬 `data/`와 `s3://ptbwa-dw/prod/lookalike/`가 같은 상대 경로를 쓴다.

```
autoencoders/<ae_version>/   pools/<pool_id>/   candidates/<period_key>/   (legacy 오토인코더만 data/models/segment_features/)
seeds/<seed>/input/          seeds/<seed>/<run_id>/{seed_segment.csv, model/, scores/}
delivery/<group>/<run_id>/<table>/   (--output-table 결과 CSV, 외부 테이블 위치)
```

## 폴더 구조

```
pipeline/   athena.py(boto3 래퍼) athena_queries.py(SQL 렌더러) encode.py paths.py
            run_seed_scenario1.py run_seed_table_multilabel.py run_ae_scenario2.py
queries/    templates/segment_features.sql(taxonomy 정본) segment/01_pool_segment.sql lib/
embedding/  세그먼트 임베딩 Autoencoder 정의/피처 빌드      train/  오토인코더 학습
inference/  임베딩 추출/병합                               scoring/  분류기 학습/스코어링(multilabel.py = 멀티라벨)
```
