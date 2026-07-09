# 임베딩 파이프라인 산출물 스키마

`querys/audience_embedding/01~06.sql`이 Athena에서 뽑아내는 가공된 CSV 6종의 스키마.
원본(raw) Athena 테이블 자체의 스키마는 [`addi_raw_data_schema.md`](addi_raw_data_schema.md)
참고 — 이 문서는 "그 원본 테이블에서 파이프라인이 실제로 뽑아 쓰는 결과물"을 다룬다.
파이프라인 실행 순서/커맨드는 [`README.md`](../README.md) §1, §2 참고.

아래 행 수/분포는 로컬에 있는 최근 실행분(`data/raw/*.csv`, 2026-07-08 추출) 기준 — SQL을
다시 실행하면 원본 로그가 늘어난 만큼 숫자는 바뀐다. **01/02/04/05는 유저 단위 5% 샘플링이
걸려 있다**(`mod(crc32(req_user_id), 100) < 5`, README §1 "주의" 참고) — 03/06은 샘플링
없이 전수.

## 산출물 개요

| # | 파일 | Grain | 행 수 | 샘플링 | 용도 |
|---|---|---|---|---|---|
| 01 | `01_top500_media_visit.csv` | 이벤트(유저×미디어 방문) | 20,863,494 | 5% | media_sequence 학습 입력 |
| 02 | `02_user_profile.csv` | 유저 1행 | 591,433 | 5% | user_profile 학습 입력 |
| 03 | `03_seed_interested_users_apr_may.csv` | 유저 1행 (T2+ 관심 유저만) | 542,511 | 없음(전수) | 스코어링 분류기의 양성 라벨(시드) |
| 04 | `04_new_users_top500_media_visit_jun.csv` | 이벤트 | 346,326 | 5% | media_sequence 추론 입력(target) |
| 05 | `05_new_users_user_profile_jun.csv` | 유저 1행 | 26,159 | 5% | user_profile 추론 입력(target) + req_user_id↔device_ifa 매핑 |
| 06 | `06_postback_max_tier_jun.csv` | ifa 1행 (postback 있었던 유저만) | 303,553 | 없음(전수) | 백테스트 라벨(실제 전환 여부) |

## 1. `01_top500_media_visit.csv` — 학습용 미디어 방문 이벤트

**소스**: `addi_bid_log_flatten`, 2026-04~05, 컴플라이언스 필터 + 5% 샘플 + 상위 500개
미디어(방문 유저 수 기준) + 세션 dedup(같은 유저·같은 미디어 30분 재방문 제거).

| 컬럼 | 타입/형식 | 설명 |
|---|---|---|
| `req_id` | string | 요청 ID |
| `req_user_id` | string | 유저 ID (그레인 키 중 하나) |
| `device_ifa` | string (UUID) | 광고 식별자 |
| `media` | string | **`app_content_genre`의 대표(첫) 장르 토큰** — `app_bundle`이 아님. distinct **113종** |
| `content_genre` | string | 콤마로 구분된 다중 장르 원본 문자열(예: `"Travel,Style & Fashion"`) — `media`는 이 값의 첫 토큰 |
| `ad_type` | string | 사실상 상수 — 20,863,494건 중 대부분 `"3"`, 결측 극소량 |
| `connection_type` | — | **항상 NULL** — `addi_bid_log_flatten`에 원본 컬럼이 없어 컬럼 계약 유지 목적으로 NULL 고정 출력 |
| `ts` | timestamp (Asia/Seoul) | 이벤트 시각 |
| `year` | string | 파티션 컬럼 그대로 통과 |

`media`/`content_genre`를 `app_bundle` 대신 콘텐츠 장르로 재정의한 이유는
[`model_architecture.md`](model_architecture.md) §2 참고 — addi CTV는 app_bundle이 통신사
IPTV 앱 3종뿐이라 다음-아이템 예측에 무의미했다.

## 2. `02_user_profile.csv` — 학습용 유저 프로필

**소스**: `addi_bid_log_flatten` 최신 로그 1건(`ROW_NUMBER() OVER (... ORDER BY created_at DESC)`),
2026-04~05, 컴플라이언스 필터 + 5% 샘플. `req_user_id` 유니크 보장.

| 컬럼 | 타입/형식 | 결측률 | 설명 |
|---|---|---|---|
| `req_user_id` | string | 0% | 그레인 키 |
| `device_ifa` | string (UUID) | 0.79% | |
| `device_os_version` | 정수(Android major, 예: 12/14/11/10) | 0% | |
| `region` | string (`KR-NN` 형식, ISO 3166-2 스타일로 보임) | **29.25%** | 최다: `KR-41`(115,888명) 등 |
| `app_bundle` | string | 0% | 정확히 3종만 — `com.skb.adui`(235,326) / `com.kt.google.ad.viewer`(189,421) / `com.lguplus.iptv.base.livetvinput`(166,686). 통신사 IPTV 앱, carrier 필드가 항상 NULL이라 대신 쓰는 통신사 식별 신호 |
| `update_dt` | date | 0% | 쿼리 실행일(`current_date`), 데이터 시점 아님 — 재실행할 때마다 바뀜 |

`device_os_version`/`device_type`/`device_make`/`device_model`/`country`/`language`/`carrier`가
빠진 이유(전부 상수 또는 거의 전부 NULL)는 SQL 상단 주석 및
[`model_architecture.md`](model_architecture.md) 참고.

## 3. `03_seed_interested_users_apr_may.csv` — 관심 유저(시드) 목록

**소스**: `addi_bid_log_flatten`(노출) ∩ `addi_postback_log`(참여), 2026-04~05, 컴플라이언스
필터 적용, **샘플링 없이 전수**. `max_engagement_tier >= 1`(T2 이상)만 포함.

| 컬럼 | 타입/형식 | 설명 |
|---|---|---|
| `req_user_id` | string | 그레인 키 |
| `device_ifa` | string (UUID) | |
| `impression_cnt` | int | 노출 횟수 (평균 328, 중앙값 206, 최대 5,337) |
| `first_exposed_at` / `last_exposed_at` | timestamp | 최초/최종 노출 시각 |
| `max_engagement_tier` | int (1~6) | `addi_postback_log.log_type` 기반 최고 도달 단계 (`i`=1 ... `v_complete`=6) |
| `interest_tier` | string | `max_engagement_tier`를 T2~T4로 재구간화. 분포: **T4_고관여(완료) 517,050명(95.3%)** / T3_중간참여 22,264명(4.1%) / T2_참여시작 3,197명(0.6%) — 시작하면 대부분 끝까지 간다 |
| `engagement_stage_cnt` | int | 도달한 distinct log_type 개수 |
| `last_engaged_at` | timestamp | 최종 참여 시각 |

**주의**: 이 파일은 542,511명 전수인데, 01/02(pool)는 5% 샘플(591,433명)이다. 학습에서
실제 양성 라벨로 쓰이는 건 이 542,511명과 pool의 교집합뿐이라, 실질 시드는 약 27,059명
수준(`model_architecture.md` §4 참고) — 표본 확대 여지가 있다는 뜻.

## 4. `04_new_users_top500_media_visit_jun.csv` — 6월 신규 유저 미디어 방문 이벤트

**소스**: `addi_bid_log_flatten`, 2026-06, "신규 유저"(2026-04~05 bid log에 없던 `req_user_id`)만,
컴플라이언스 필터 + 5% 샘플. 컬럼 구조는 01과 동일하지만 **top500 재필터링을 하지 않는다** —
01에서 학습한 `vocab_media.json`을 그대로 써야 해서, 그 vocab에 없는 값은 추론 시 `<UNK>`로
인코딩된다.

| 컬럼 | 값 |
|---|---|
| 행 수 | 346,326 |
| distinct `req_user_id` | 25,451명 |
| distinct `media` | 90종 (01에서 학습한 113종 vocab의 부분집합) |
| `ad_type` | 346,321건이 `"3"`, 결측 5건 — 01과 동일하게 사실상 상수 |
| `connection_type` | 100% NULL |
| 유저당 이벤트 수 | 평균 13.6, 중앙값 4, 최대 468 |

컬럼 정의는 01과 동일. `media_sequence`는 이벤트 5개 미만 유저를 추론에서 제외하므로
(`config.MIN_SEQ_LEN`, `inference/media_sequence.py`), 25,451명 중 일부는 최종 임베딩에서
빠진다.

## 5. `05_new_users_user_profile_jun.csv` — 6월 신규 유저 프로필

**소스**: `addi_bid_log_flatten` 최신 로그 1건, 2026-06, "신규 유저"만(04와 동일 정의),
컴플라이언스 필터 + 5% 샘플. 컬럼 구조는 02와 완전히 동일.

| 컬럼 | 결측률 |
|---|---|
| `req_user_id` | 0% |
| `device_ifa` | 1.51% |
| `device_os_version` | 0% |
| `region` | **0.43%** — 02(29.25%)보다 훨씬 낮음, 시기/트래픽 믹스 차이로 추정 |
| `app_bundle` | 0% |
| `update_dt` | 0% |

행 수 26,159명 — 04의 distinct `req_user_id`(25,451명)와 정확히 일치하지 않는다. 프로필은
있지만 top500 미디어 방문 이벤트가 하나도 없는 유저, 혹은 그 반대 케이스가 있을 수 있어
(둘 다 세션 dedup·5% 샘플링이 각자 독립적으로 걸림) — `scoring`에서 두 임베딩을
`req_user_id`로 inner join할 때 이 차이만큼 자연히 걸러진다(`scoring/fused_embeddings.py`).
이 파일은 스코어링 결과와 백테스트 라벨(06)을 이어주는 `req_user_id ↔ device_ifa` 매핑
소스로도 쓰인다(`evaluation.backtest --id-map`).

## 6. `06_postback_max_tier_jun.csv` — 백테스트용 6월 postback 요약

**소스**: `addi_postback_log`, 2026-06 전체, **컴플라이언스 필터/신규 유저 필터 둘 다 없음**
— 04/05가 이미 동의 유저·신규 유저로 걸러놨으므로, 여기서는 그 유저들의 실제 전환 이력만
조회하면 된다는 설계(SQL 주석 참고). 즉 이 303,553명은 "6월 신규 유저"가 아니라 **6월에
postback을 남긴 모든 유저**(기존 유저 포함)다 — 05의 `device_ifa`와 교집합인 사람만 실제
백테스트 라벨로 쓰인다.

| 컬럼 | 타입/형식 | 설명 |
|---|---|---|
| `ifa` | string (UUID) | `device_ifa`와 동일 체계 (`evaluation/backtest.py --map-to-col`로 연결) |
| `max_tier` | int (0~6) | 최고 도달 tier. 분포: 0(16) / 1(1,433) / 2(1,331) / 3(1,257) / 4(2,253) / 5(34,573) / **6(262,690, 86.6%)** — 03과 마찬가지로 시작하면 대부분 완료까지 간다 |

`evaluation.backtest --label-threshold`가 이 `max_tier`를 기준값과 비교해 이진 라벨(반응/
비반응)을 만든다 — 해석 방법은 [`output_analysis.md`](output_analysis.md) 참고.

## 데이터 흐름 요약

```
[4~5월 전체 노출 풀]                    [6월 신규 유저]
01 이벤트 20.9M건 ─┐                    04 이벤트 346K건 ─┐
02 유저 591,433명 ─┤ (5% 샘플)          05 유저 26,159명 ─┤ (5% 샘플)
                    │                                     │
                    ▼                                     ▼
        train.user_profile / media_sequence      inference.user_profile / media_sequence
                    │                                     │
                    ▼                                     ▼
          pool 임베딩(user_profile_apr_may,        target 임베딩(user_profile_jun_new,
          media_sequence_apr_may)                  media_sequence_jun_new)
                    │                                     │
03 시드 542,511명(전수) ──┐                               │
  → pool과 교집합만 실질 사용(~27,059명)                  │
                    ▼                                     ▼
        scoring.train_supervised_lookalike ──────▶ scoring.infer_supervised_lookalike
                                                            │
                                                            ▼
                                          supervised_lookalike_scored_jun.csv
                                                            │
06 postback 303,553명(전수, 신규 유저 한정 아님) ──────────┤ (05의 device_ifa와 교집합만)
                                                            ▼
                                          evaluation.backtest 결과 (output_analysis.md)
```
