# seed/ — 피엘라벤 seed 기반 신규 유저 룩어라이크

외부에서 확보한 브랜드 seed 리스트(현재: 피엘라벤)를 두고, propfit 소스에서 비슷한
신규 유저를 찾는 트랙. 실행 순서·산출물·설계 결정·모델 구조는 `../summary_note/`의
최신 실험 요약 문서 참고(`seed/docs/`는 2026-08-04 삭제됨 — segment/media 트랙 분리
이후 내용이 낡아서 정리). 조사 과정(ID 공간 크로스워크, 표본 버그 등)은 저장소 루트의
[`../eda/`](../eda/) 참고.

이 폴더는 **독립 작업 루트**다 — 저장소 루트가 아니라 여기로 `cd` 한 뒤 실행한다
(패키지 최상위가 여기 `seed/`이므로).

```
cd seed
..\.venv\Scripts\python.exe -m embedding.segment_features.build_features
..\.venv\Scripts\python.exe -m train.segment_features
..\.venv\Scripts\python.exe -m inference.segment_features

..\.venv\Scripts\python.exe -m scoring.train_lookalike --variant segment
..\.venv\Scripts\python.exe -m scoring.infer_lookalike --variant segment --top-pct 10
```

## 신규 seed가 들어왔을 때

새 브랜드 seed 리스트(CSV)가 들어오면 아래 순서로 진행한다(je seed, 2026-08-19에서 확립된
패턴 — `pipeline/`에 자동화돼 있음). 1)/3)은 Athena SQL이라 이 repo에 접근 권한이 없어
사용자가 콘솔에서 직접 실행해야 한다(CLAUDE.md "데이터를 얻는 방법" 참고) — 그 외에는
아래 명령을 그대로 실행하면 된다.

```
cd seed

# 1) seed 테이블 등록 + ID 공간 확인 쿼리 생성
..\.venv\Scripts\python.exe -m pipeline.generate_seed_queries register --seed-name <name> --s3-path s3://ptbwa-dw/prod/seed_<name>/ --csv-filename <원본.csv> --header
# -> queries/01_create_seed_table_<name>.sql, ../eda/queries/id_space_check/NN_seed_<name>_id_space_check.sql
#    생성됨. 원본 CSV를 그 S3 경로에 올리고, 두 SQL을 Athena 콘솔에서 순서대로 실행한다.

# 2) id_space_check 결과 한 줄(seed_total ~ seed_matches_skb_uuid, 6개 숫자)을 그대로 붙여넣어
#    직접/크로스워크를 자동 판정 -> ad_id/segment 쿼리 생성
..\.venv\Scripts\python.exe -m pipeline.generate_seed_queries resolve --seed-name <name> --matches <seed_total> <bidlog> <skp_direct> <skb_ad_id> <skb_platform_ad_id> <skb_uuid>
# -> queries/02_create_seed_ad_id_table_<name>.sql, queries/segment/02_seed_segment_<name>.sql
#    생성됨. "판정 불가(ambiguous)"면 직접 id_space_check 결과를 보고
#    02_create_seed_ad_id_table_<name>.sql을 수동 작성할 것(je/피엘라벤 버전 참고).
#    두 SQL을 Athena 콘솔에서 순서대로 실행하고 seed_segment_<name>.csv를 ../data/seed/에 받는다.

# 3) candidate 정의(bid log 기간 + region=KR/OS=Android + skp 세그먼트 보유 + 기존 seed 전부
#    제외) + segment 피처 추출을 CREATE TABLE 없이 SELECT 하나로 생성(2026-08-26부터 —
#    옛 03_create_candidate_table.sql+04_candidate_segment.sql 2단계 방식은 이미 실행된
#    seed의 provenance라 그대로 둠). 기간은 시작월 1일부터, 같은 연도 안에서만 지원.
..\.venv\Scripts\python.exe -m pipeline.generate_seed_queries candidate --seed-name <name> --period-start <YYYY-MM-01> --period-end <YYYY-MM-DD>
# -> queries/segment/04_candidate_segment_<name>.sql 생성됨. Athena 콘솔에서 실행하고
#    (테이블 생성 없이 바로 결과 다운로드) ../data/seed/candidate_segment.csv로 받는다.

# 4) 인코딩(기존 학습된 Autoencoder로 forward만) -> 분류기 학습(seed=1/pool=0) -> candidate
#    스코어링 -> 상위 N% 추출을 한 번에 실행
..\.venv\Scripts\python.exe -m pipeline.run_new_seed_pipeline --seed-name <name> --top-pct 10
# -> ../data/models/lookalike_classifier_<name>/candidate_scores.csv,
#    candidate_scores_top10pct.csv
```

pool은 기본으로 기존 피엘라벤 pool(`pool_segment.csv`)을 재사용한다(신규 seed 규모가
pool을 새로 뽑아야 할 만큼 크지 않다는 판단이 서면 그대로 두고, 아니라면
`run_new_seed_pipeline.py --pool-ids-csv`로 대체). 자세한 설계 근거(왜 pool/candidate를
재사용하는지, WeightedRandomSampler를 쓰는 이유 등)는 `../summary_note/`의 je 실험 요약
문서 참고.

## 겹치는 seed 여러 개를 한 번에 — 멀티라벨(멀티헤드) 분류기

서로 겹치는 seed 여러 개(현재: 군 관련 4종 `military` — 전역남성/부모/곰신/입대예정)는
seed별 이진 분류기 대신 공유 trunk + 라벨별 sigmoid 헤드 하나로 학습한다. 라벨 구성은
`scoring/config.py`의 `MULTILABEL_VARIANTS`. 각 seed의 1)~2) 단계(Athena)는 위와 같고,
candidate는 전 seed를 제외한 쿼리 하나를 공용으로 쓴다.

```
cd seed
..\.venv\Scripts\python.exe -m pipeline.run_multilabel_pipeline --variant military --top-pct 10
# (개별 실행: scoring.train_multilabel / scoring.infer_multilabel --variant military)
```

산출물(`../data/models/lookalike_multilabel_<variant>/`): `candidate_scores.csv`(전 후보 ×
라벨별 `score_<key>`/`pct_<key>`/`top_label`), `candidate_scores_top<N>pct.csv`(라벨별 상위 N%
합집합 + `in_top_<key>`/`selected_labels`), `top<N>pct_<key>.csv`(라벨별), `labels.json`(라벨
정의 + 검증 AUC). `score_*`는 pos_weight 학습이라 라벨 간 비교 불가 — 라벨 간 비교는 `pct_*`로.

## 폴더 구조

```
queries/
  lib/            propfit 피처 추출 라이브러리(01_user_profile/11_user_embedding_features)
  01~07*.sql       seed 파이프라인(seed 테이블 등록 → 크로스워크 → 피처 추출 → pool/후보)
embedding/
  common/          공용 유틸(vocab/device/train_config/config_file)
  segment_features/  skp 세그먼트 임베딩(Autoencoder) 모델 정의
    build_features_incremental.py  기존 vocab/lookup으로 population 하나만 인코딩(재학습 없음)
train/
  segment_features.py   위 세그먼트 모델 학습 스크립트
inference/
  segment_features.py   학습된 세그먼트 모델로 임베딩(z) 추출 스크립트
  append_embeddings.py  임베딩 CSV를 기존 segment_embeddings.csv에 중복 없이 append
scoring/
  config.py/model.py/dataset.py   지도학습 lookalike 분류기 정의(Variant로 seed마다 분리)
  train_lookalike.py    seed=1/pool=0으로 분류기 학습(--variant)
  infer_lookalike.py    candidate 스코어링 + 상위 후보 추출(--variant)
  train_multilabel.py / infer_multilabel.py   멀티라벨(멀티헤드) 분류기 학습/스코어링
pipeline/
  generate_seed_queries.py   신규 seed의 Athena SQL(seed 테이블/id space 확인/ad_id/segment/
                              candidate 정의+피처 추출)을 템플릿으로 생성(register/resolve/candidate)
  run_new_seed_pipeline.py   신규 seed의 Python 단계(인코딩 -> 학습 -> 스코어링 -> top N)를
                              한 번에 실행 — "신규 seed가 들어왔을 때" 절 참고
  run_multilabel_pipeline.py 멀티라벨 variant의 인코딩 -> 학습 -> 라벨별 top N 일괄 실행
config/
  train_config.example.json
docs/
  README.md              실행 순서 + 현재 산출물 + 설계 결정
  model_architecture.md  모델 구조 스펙 + 스코어링 파이프라인 + 3-variant 비교 요약
```
