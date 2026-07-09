# 파이프라인 산출물 스키마

`querys/pipeline/01~10.sql`이 Athena에서 뽑아내는 가공된 CSV 10종의 스키마. 원본(raw) Athena
테이블 자체의 스키마는 [`addi_raw_data_schema.md`](addi_raw_data_schema.md) 참고 — 이 문서는
"그 원본 테이블에서 파이프라인이 실제로 뽑아 쓰는 결과물"을 다룬다. 실행 순서/커맨드는
[`README.md`](../README.md) §1, §2 참고. 전환 정의(IP 매칭)를 왜 이렇게 잡았는지는
[`querys/pipeline/README.md`](../querys/pipeline/README.md)와
[`docs/_archive/202607091533.md`](_archive/202607091533.md) 참고.

아래 행 수/분포는 로컬에 있는 최근 실행분(2026-07-09 추출) 기준 — SQL을 다시 실행하면 원본
로그가 늘어난 만큼 숫자는 바뀐다. **01/02는 유저 단위 5% 샘플링이 걸려 있다**
(`mod(crc32(req_user_id), 100) < 5`, README §1 "주의" 참고) — 03~10은 샘플링 없이 전수.
09/10은 아직 실행 전이라 행 수 미기재(실행 후 이 표를 갱신할 것).

## 산출물 개요

| # | 파일 | Grain | 행 수 | 샘플링 | 용도 |
|---|---|---|---|---|---|
| 01 | `01_pool_profile_apr_may.csv` | 유저 1행 | 591,433 | 5% | user_profile 학습 입력 + pool |
| 02 | `02_pool_media_apr_may.csv` | 이벤트 | 20,863,494 | 5% | media_sequence 학습 입력 + pool |
| 03 | `03_seed_users_apr_may.csv` | 유저 1행 | 485 | 없음(전수) | 스코어링 분류기의 양성 라벨(시드) |
| 04 | `04_seed_profile_apr_may.csv` | 유저 1행 | 396 | 없음(전수) | 시드 유저 프로필(층화 pool 병합용) |
| 05 | `05_seed_media_apr_may.csv` | 이벤트 | 51,158 | 없음(전수) | 시드 유저 미디어 방문(층화 pool 병합용) |
| 06 | `06_backtest_labels_jun.csv` | ifa 1행 | 303,554 | 없음(전수) | 백테스트 라벨(IP 매칭 전환 여부) |
| 07 | `07_scoring_target_profile_jun.csv` | 유저 1행 | 284,940 | 없음(전수) | user_profile 추론 입력(스코어링 대상, 백테스트용) |
| 08 | `08_scoring_target_media_jun.csv` | 이벤트 | 17,531,914 | 없음(전수) | media_sequence 추론 입력(스코어링 대상, 백테스트용) |
| 09 | `09_new_users_profile_jun.csv` | 유저 1행 | (미실행) | 없음(전수) | user_profile 추론 입력(실제 후보 리스트, leakage 없음) |
| 10 | `10_new_users_media_jun.csv` | 이벤트 | (미실행) | 없음(전수) | media_sequence 추론 입력(실제 후보 리스트, leakage 없음) |

## 1. `01_pool_profile_apr_may.csv` — pool 유저 프로필

**소스**: `addi_bid_log_flatten` 최신 로그 1건(`ROW_NUMBER() OVER (... ORDER BY created_at DESC)`),
2026-04~05, 컴플라이언스 필터 + 5% 샘플. `req_user_id` 유니크 보장.

| 컬럼 | 타입/형식 | 결측률 | 설명 |
|---|---|---|---|
| `req_user_id` | string | 0% | 그레인 키 |
| `device_ifa` | string (UUID) | 0.79% | |
| `device_os_version` | 정수(Android major, 예: 12/14/11/10) | 0% | |
| `region` | string (`KR-NN` 형식, ISO 3166-2 스타일) | 29.25% | 최다: `KR-41`(115,888명) 등 |
| `app_bundle` | string | 0% | 정확히 3종만 — `com.skb.adui`(235,326) / `com.kt.google.ad.viewer`(189,421) / `com.lguplus.iptv.base.livetvinput`(166,686). 통신사 IPTV 앱, carrier 필드가 항상 NULL이라 대신 쓰는 통신사 식별 신호 |
| `update_dt` | date | 0% | 쿼리 실행일(`current_date`), 데이터 시점 아님 — 재실행할 때마다 바뀜 |

빠진 필드(`device_type`/`device_make`/`device_model`/`country`/`language`/`carrier` 등)의
사유는 SQL 상단 주석 및 [`model_architecture.md`](model_architecture.md) 참고.

## 2. `02_pool_media_apr_may.csv` — pool 미디어 방문 이벤트

**소스**: `addi_bid_log_flatten`, 2026-04~05, 컴플라이언스 필터 + 5% 샘플 + 상위 500개
미디어(방문 유저 수 기준) + 세션 dedup(같은 유저·같은 미디어 30분 재방문 제거).

| 컬럼 | 타입/형식 | 설명 |
|---|---|---|
| `req_id` | string | 요청 ID |
| `req_user_id` | string | 유저 ID (그레인 키 중 하나) |
| `device_ifa` | string (UUID) | 광고 식별자 |
| `media` | string | `app_content_genre`의 대표(첫) 장르 토큰 — `app_bundle`이 아님. distinct 113종 |
| `content_genre` | string | 콤마로 구분된 다중 장르 원본 문자열(예: `"Travel,Style & Fashion"`) |
| `ad_type` | string | 사실상 상수 — 대부분 `"3"` |
| `connection_type` | — | 항상 NULL — `addi_bid_log_flatten`에 원본 컬럼이 없어 컬럼 계약 유지 목적으로 NULL 고정 출력 |
| `ts` | timestamp (Asia/Seoul) | 이벤트 시각 |
| `year` | string | 파티션 컬럼 그대로 통과 |

`media`/`content_genre`를 `app_bundle` 대신 콘텐츠 장르로 재정의한 이유는
[`model_architecture.md`](model_architecture.md) §2 참고.

## 3. `03_seed_users_apr_may.csv` — 시드(양성) 유저 목록

**소스**: `addi_postback_log`(ip) ∩ `"prod_addi_conv".raw_conv_web(_imp)`(mall_ip), 2026-04~05,
IP+cmp_no 일치(시간창 제한 없음) → `addi_bid_log_flatten`에서 컴플라이언스 필터 적용해
req_user_id 매핑. **샘플링 없이 전수**.

| 컬럼 | 타입/형식 | 설명 |
|---|---|---|
| `req_user_id` | string | 그레인 키 |
| `device_ifa` | string (UUID) | |

**주의**: 이 485명 전수인데, 01/02(pool)는 5% 샘플(591,433명)이다. 그대로면 pool과의
교집합이 ~20명 수준으로 줄어 학습이 사실상 불가능 — 그래서 04/05로 이 유저들만 별도 전수
조회해서 `scoring.build_stratified_pool`로 pool에 강제 병합한다(README §2-3).

## 4. `04_seed_profile_apr_may.csv` / 5. `05_seed_media_apr_may.csv` — 시드 유저 전수 프로필/미디어

**소스**: 03의 유저만 대상으로, 01/02와 동일한 로직(컬럼 계약 동일)이지만 **5% 샘플링 없음**.
04는 396명(일부 유저는 4~5월 bid log에서 컴플라이언스 필터를 통과하는 최신 행이 없어 03의
485명보다 적음), 05는 51,158개 이벤트(distinct req_user_id 484명, 이 중 이벤트 5개 미만인
56명은 `inference.media_sequence`가 자동 제외).

## 6. `06_backtest_labels_jun.csv` — 백테스트용 6월 IP 매칭 전환 라벨

**소스**: `addi_postback_log`(ip), 2026-06 전체, **컴플라이언스 필터 없음**(07/08이 이미
동의 유저로 필터링해뒀으므로) × `"prod_addi_conv".raw_conv_web(_imp)`(mall_ip). 303,554명
(2026-06 postback 발생 유저 전원) 전수.

| 컬럼 | 타입/형식 | 설명 |
|---|---|---|
| `ifa` | string (UUID) | `device_ifa`와 동일 체계 |
| `conv_matched_ip_cmp_any_window` | 0/1 | IP+cmp_no 일치, 시간창 제한 없음. 양성 30명(0.0099%) |
| `conv_matched_ip_cmp_7d` | 0/1 | 위에 7일 시간창 추가. 양성 4명 |
| `conv_matched_ip_cmp_30d` | 0/1 | 위에 30일 시간창 추가. 양성 27명 |
| `conv_matched_ip_any_cmp_any_window` | 0/1 | cmp_no 무시, IP만 일치. 양성 170명(0.056%) — **백테스트 기본 라벨** |
| `conv_matched_order_only` | 0/1 | `ev='order'`(실구매)로 제한. 양성 0명 — order 이벤트가 시스템 전체에 ~60건뿐이라 참고용 |

`evaluation.backtest --label-col`로 위 후보 중 하나를 골라 이진 라벨을 만든다 — 표본
크기와 정밀도(cmp_no 요구 여부) 트레이드오프는 [`README.md`](../README.md) §2-5 참고.

## 7. `07_scoring_target_profile_jun.csv` / 8. `08_scoring_target_media_jun.csv` — 6월 스코어링 대상

**소스**: `addi_postback_log`(ifa) 2026-06 발생 유저 전원을 `addi_bid_log_flatten`(device_ifa)의
2026-06 로그와 매칭. 컴플라이언스 필터만 적용, **5% 샘플링 없음**(postback 유저 집합 자체가
이미 30만 명대라 전수 조회해도 Athena 부담이 크지 않음). 컬럼 구조는 01/02와 각각 동일.

07은 284,940명, 08은 17,531,914개 이벤트(distinct req_user_id 303,708명 — 06의 라벨 모집단
303,554명과 거의 같지만 완전히 일치하지는 않는다, bid log 매칭 여부에 따라 약간의 차이).

**주의**: 이 유저들은 이미 postback을 낸 사람들이라, 4~5월 pool(01/02)이나 시드(03~05)에
같은 사람이 있을 수 있다 — 07/08 기반 백테스트에는 학습-검증 겹침(leakage) 위험이 있다
(README §2-5 "주의" 참고). 겹침 없는 순수 후보군이 필요하면 09/10을 쓴다.

## 9. `09_new_users_profile_jun.csv` / 10. `10_new_users_media_jun.csv` — 6월 신규 유저(실제 후보 리스트)

**소스**: `addi_bid_log_flatten`, 2026-06, 2026-04~05 bid log에 전혀 없던 `req_user_id`만
(신규 유저), 컴플라이언스 필터, **5% 샘플링 없음**(실제 후보 리스트 산출 단계이므로 전수).
컬럼 구조는 각각 01/02와 동일.

07/08(이미 반응한 postback 유저, 백테스트/검증용)과 달리 이 유저들은 정의상 4~5월 pool/
시드에 등장할 수 없다 — 학습 때 본 적 없는 순수 held-out 집합이라, 이걸 스코어링한 결과
(`data/embeddings/new_users_scored_jun.csv`, README §2-6)가 leakage 걱정 없는 실제 타겟팅
후보 리스트다.

## 데이터 흐름 요약

```
[4~5월 pool(5% 샘플)]              [4~5월 시드(전수)]              [6월 스코어링 대상(전수)]
01 프로필 591,433명 ─┐             03 유저 목록 485명               07 프로필 284,940명 ─┐
02 이벤트 20.9M건   ─┤             04 프로필 396명 ─┐               08 이벤트 17.5M건   ─┤
                     │             05 이벤트 51,158건┤                                   │
                     ▼                              ▼                                   ▼
      train.user_profile/media_sequence    inference.user_profile/media_sequence  inference.user_profile/media_sequence
                     │                              │                                   │
                     ▼                              ▼                                   ▼
          pool_profile/pool_media.csv      seed_profile/seed_media.csv      scoring_target_profile/media_jun.csv
                     │                              │                                   │
                     └──── scoring.build_stratified_pool (음성 5% + 양성 전수) ────┐     │
                                        │                                          │     │
                                        ▼                                          │     │
                         pool_profile/media_stratified.csv                         │     │
                                        │                                          │     │
                     03 시드 485명(전수, --seed-ids) ─────┐                        │     │
                                        ▼                 ▼                        │     │
                          scoring.train_supervised_lookalike ──────────▶ scoring.infer_supervised_lookalike
                                                                                    │     │
                                                                                    ▼     │
                                                                        scored_jun.csv    │
                                                                                    │     │
06 IP 매칭 라벨 303,554명(전수) ───────────────────────────────────────────────────┤ (07의 device_ifa와 매핑)
                                                                                    ▼
                                                              evaluation.backtest 결과
```
