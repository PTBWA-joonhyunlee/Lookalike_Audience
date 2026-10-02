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

## 시나리오 2 — 오토인코더 재학습 (미구현)

pool 조건 입력 -> pool segment 추출 -> 오토인코더 재학습. 이 단계가 `data/pools/`, `data/autoencoders/`를 만든다.

## 경로 규칙 (`pipeline/paths.py`)

로컬 `data/`와 `s3://ptbwa-dw/prod/lookalike/`가 같은 상대 경로를 쓴다.

```
autoencoders/<ae_version>/   pools/<pool_id>/   candidates/<period_key>/
seeds/<seed>/input/          seeds/<seed>/<run_id>/{seed_segment.csv, model/, scores/}
```

## 폴더 구조

```
pipeline/   athena.py(boto3 래퍼) athena_queries.py(SQL 렌더러) encode.py paths.py run_seed_scenario1.py
queries/    templates/segment_features.sql(taxonomy 정본) segment/01_pool_segment.sql lib/
embedding/  세그먼트 임베딩 Autoencoder 정의/피처 빌드      train/  오토인코더 학습
inference/  임베딩 추출/병합                               scoring/  분류기 학습/스코어링
```
