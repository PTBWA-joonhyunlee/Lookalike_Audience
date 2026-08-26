# shoplinker Seed(231,090명) segment 임베딩 기반 lookalike 스코어링 요약

## 0. 목표

새 브랜드 seed(`data/seed/00_shoplinker_seed.csv`, raw GAID 232,366명)를 피엘라벤
segment 트랙에 붙여 lookalike 후보를 뽑았다. media 트랙은 이번엔 진행하지 않는다(요청에
따라 skip — `media/03_seed_media_shoplinker.sql`은 생성만 해두고 실행하지 않음).
segment 임베딩은 **재학습 없이** 기존 `segment_features` Autoencoder로 인코딩만 했고
(`build_features_incremental.py` → `inference.segment_features` → `append_embeddings.py`),
lookalike 분류기(`segment_shoplinker` variant)는 이번에 처음 학습했다(1회) — 이후
top15%/top30% 추출은 그 모델을 그대로 재사용(재학습 없음)했다.

### 0-1. pool/candidate 추출 방식 — 기간·필터·샘플링

| | seed(shoplinker) | pool | candidate |
|---|---|---|---|
| 기간 | skp 최신 스냅샷(기간 파티션 필터 없음) | 2026-04~05 | **2026-06~08/24**(shoplinker 전용, 04~05월 학습 기간 제외) |
| 대상 | `seed_shoplinker_ad_id`(231,090명) ∩ skp 세그먼트 매칭 | 전체 모집단(seed_piellaven·seed_je 제외, **shoplinker는 미제외** — 5절 참고) | KR + Android(`device_osv` 숫자 필터) + skp 세그먼트 매칭 + seed_piellaven·seed_je·seed_shoplinker 전부 제외 |
| ID 공간 | raw GAID 직접(크로스워크 불필요 — 1절 판정 결과) | raw GAID | raw GAID |
| 샘플링 | 전수(231,090명) | 5%(`mod(crc32(device_ifa),1000)<50`) | 100%(샘플링 없음) |
| 쿼리/테이블 | [`segment/02_seed_segment_shoplinker.sql`](../seed/queries/segment/02_seed_segment_shoplinker.sql) | [`segment/01_pool_segment.sql`](../seed/queries/segment/01_pool_segment.sql)(재사용) | [`segment/03_create_candidate_table.sql`](../seed/queries/segment/03_create_candidate_table.sql)(`candidates_shoplinker_20260601_0824`)+[`04_candidate_segment.sql`](../seed/queries/segment/04_candidate_segment.sql) |

## 1. ID 공간 판정

[`eda/queries/29_seed_shoplinker_id_space_check.sql`](../eda/queries/29_seed_shoplinker_id_space_check.sql) 결과:

| seed_total | bidlog | skp_direct | skb_ad_id | skb_platform_ad_id | skb_uuid |
|---|---|---|---|---|---|
| 232,366 | 154,323 (66.4%) | 231,090 (99.4%) | 232,366 (100%) | 0 | 0 |

direct 매칭률(skp_direct/skb_ad_id 중 최댓값) 100% — 임계값(10%) 이상, crosswalk 후보는
0% — `pipeline/generate_seed_queries.py`가 **mode=direct**로 자동 판정했다. 즉 크로스워크
없이 seed 원본 device_ifa를 그대로 raw GAID로 쓴다(je·피엘라벤과 달리 이 seed는 이미
GAID 공간에 있었다).

## 2. population 규모

| | seed | pool | candidate |
|---|---|---|---|
| population 규모(각 `*_segment*.csv` 행수) | 231,090 | 2,549,024 | 4,219,424 |

seed 231,090명은 등록된 232,366명 중 skp 세그먼트가 있는 인원만이다(segment 쿼리 자체가
세그먼트 매칭 여부로 population을 정의 — je/피엘라벤과 동일한 제약).

## 3. seed/pool/candidate 겹침 점검

| 항목 | 값 |
|---|---|
| candidate ∩ pool | **209,975명**(candidate의 4.98% — pool의 5% 해시 표본 비율 그대로, pool의 8.24%) |
| candidate ∩ seed_shoplinker | **0명**(candidate 정의에 seed_shoplinker 제외 조건이 반영됨) |
| pool ∩ seed_shoplinker | **4,413명**(pool의 0.17%) |

candidate와 pool의 겹침(209,975명)은 pool이 기간 필터 없이 skp 전체에서 5% 해시로 뽑히는
구조상 candidate 기간을 어떻게 잡아도 발생한다(je 8/25 문서에서 이미 확인된 패턴, score
분포에 실질적 영향 없음이 그때 실측됨 — 이번엔 재검증하지 않았다). pool ∩ seed_shoplinker
(4,413명)는 **라벨링 단계에서 자동으로 seed 쪽으로 정리된다** — `scoring/dataset.py`가
`embeddings[isin(seed_ids | pool_ids)]`로 합집합을 만든 뒤 `label = isin(seed_ids)`로
라벨을 매기므로, 겹치는 디바이스는 pool(label=0)이 아니라 seed(label=1)로만 카운트된다
(아래 4절 학습 표본의 pool=2,544,611 = 2,549,024 − 4,413과 정확히 일치 — 실측 확인됨).
즉 이 겹침 때문에 같은 디바이스가 label=0/1 양쪽에 동시에 들어가는 leakage는 없다.

## 4. 모델 학습/스코어링 결과

- **variant**: `segment_shoplinker`(`scoring/config.py`에 상수로 등록하지 않고
  `run_new_seed_pipeline.py`가 즉석 생성) — seed=1/pool=0 라벨로 신규 학습(20 epoch).
- **학습 표본**: 2,775,701명(seed=231,090, pool=2,544,611 — 3절 참고), embed_dim=32.
- **val_auc**: epoch1 0.9296 → epoch20 **0.9380**(단조 개선, overfitting 징후 없음).
- **candidate 스코어링**: 4,219,424명 전원(임베딩 누락 0명), mean=0.2506, median=0.1009,
  min=0.0000, max=1.0000.

**top N% cutoff**(요청받은 10/15/30% 외에 참고용으로 50~1%까지 같이 냄 — 다른 컷오프가
필요하면 `candidate_scores.csv`에서 바로 다시 뽑을 수 있다):

| top N% | cutoff | 인원 |
|---|---|---|
| 50% | 0.1009 | 2,109,950 |
| 30% | 0.2446 | 1,265,827 |
| 20% | 0.4424 | 843,885 |
| **15%** | **0.6368** | **632,914** |
| **10%** | **0.8377** | **421,943** |
| 5% | 0.9274 | 210,972 |
| 1% | 0.9735 | 42,195 |

## 5. 산출물

| 파일 | 내용 |
|---|---|
| `data/models/lookalike_classifier_shoplinker/model.pt` | 학습된 분류기(20 epoch, val_auc 0.9380) |
| `data/models/lookalike_classifier_shoplinker/candidate_scores.csv` | 전체 4,219,424명(score 내림차순) |
| `data/models/lookalike_classifier_shoplinker/candidate_scores_top10pct.csv` | 상위 10% = 421,943명, score≥0.8377 |
| `data/models/lookalike_classifier_shoplinker/candidate_scores_top15pct.csv` | 상위 15% = 632,914명, score≥0.6368 |
| `data/models/lookalike_classifier_shoplinker/candidate_scores_top30pct.csv` | 상위 30% = 1,265,827명, score≥0.2446 |

## 6. 한계 / 이번에 확인하지 않은 것

- **profile 분석 미실시**: 연령/성별/product_interest 등 세그먼트 성향 비교(je 8/19
  문서 1~3절에 해당하는 분석)는 이번엔 요청받지 않아 돌리지 않았다. top-pct 후보의
  실제 성향(어떤 세그먼트가 두드러지는지)은 아직 확인 전이다.
- **pool은 shoplinker를 제외하지 않음**: `01_pool_segment.sql`을 손대지 않아 pool과
  shoplinker seed 사이에 4,413명(0.17%) 겹침이 남아있다 — 3절에서 확인했듯 학습
  라벨링 단계에서 자동으로 seed 쪽으로 정리되어 leakage는 없지만, pool 자체를 완전히
  정리하려면 `seed_shoplinker_ad_id` 제외 조건을 추가해 pool을 재추출해야 한다
  (je 8/19 문서에서도 동일한 한계가 언급됨).
- **media 트랙 미진행**: `media/03_seed_media_shoplinker.sql`은 생성만 됐고 실행하지
  않았다. media candidate 제외 조건(`media/04_create_candidate_table_media.sql`)에도
  shoplinker가 아직 반영되지 않았다 — 나중에 media/combined variant가 필요해지면
  그때 처리할 것.
- **목표 인원수 미지정**: 이번엔 "몇 명이 필요하다"는 목표 없이 10/15/30%만 뽑았다.
  특정 인원수가 필요해지면 4절 cutoff 표에서 역산하거나 `infer_lookalike.py`류
  스코어링을 다시 돌리지 않고 `candidate_scores.csv`에서 바로 뽑으면 된다(재학습·재스코어링
  불필요).
