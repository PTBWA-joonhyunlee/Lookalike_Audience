# ADDI 데이터 정합성 검증 리포트

- **검증 대상 기간**: 2026-06-01 ~ 2026-06-07 (로그 테이블 `year/month/day` 파티션 기준), 마스터 테이블(advertisement/business)은 스냅샷 전체
- **실행 환경**: AWS Athena
- **쿼리 원본**: `querys/athena_validation_queries/`
- **실행 결과 원본**: `sample_data/valiation/*.csv`
- **미실행**: C4(`postback_deal_id_missing_in_bid`) — 결과 없음, 별도 재실행 필요

## 요약

| 심각도 | 항목 수 | 내용 |
|---|---|---|
| 🔴 주의 필요 | 3 | D3(날짜 역전), D6(사업자번호 placeholder), D8/퍼널 역전(`v_firstQ` 이상치) |
| 🟡 확인 권장 | 4 | B2(대량 중복 이벤트), C3(cmp_no 불일치 1건), F1(06-03 postback 급감), F2(postback 없는 media_id) |
| 🟢 정상 | 이하 전체 | PK 무결성, FK 무결성, 값 도메인, 파티션 정합성, 가격 범위 등 |

---

## 🔴 주의가 필요한 발견

### 1. D3 — advertisement 날짜 역전 (1건)
```
adspid=10028, startdt=2026-02-04 18:31:00, enddt=2025-12-26 23:59:00
```
시작일이 종료일보다 늦습니다. 입력 실수이거나 마이그레이션 시 연도가 잘못 들어간 것으로 추정됩니다. **캠페인 운영 로직(활성 여부 판단 등)에 영향을 줄 수 있어 원본 데이터 수정이 필요합니다.**

### 2. D6 — business.businessnum 비정상 값 (1건)
```
businessid=109, businessnum="0"
```
사업자등록번호가 `"0"`이라는 placeholder 값으로 들어가 있습니다. 세금계산서 발행/정산 시 문제가 될 수 있습니다.

### 3. D8 — postback 비디오 퀀타일 퍼널 역전 (`v_firstQ` 이상치)
정상적인 비디오 재생 퍼널은 `v_start ≥ v_firstQ ≥ v_mid ≥ v_thirdQ ≥ v_complete` 순으로 단조 감소해야 하는데, 실측 값은 다음과 같습니다.

| 이벤트 | 건수 |
|---|---:|
| v_start | 120,755 |
| v_progress | 120,301 |
| **v_thirdQ (75%)** | **119,010** |
| v_mid (50%) | 113,198 |
| v_complete (100%) | 109,931 |
| **v_firstQ (25%)** | **108,729** |

`v_firstQ`(25% 지점) 건수가 `v_mid`(50%)·`v_thirdQ`(75%)보다 낮고, 심지어 `v_complete`(100%)보다도 낮습니다. 25% 지점을 통과해야 50%/75%/완료 이벤트가 발생하는 게 정상이므로, **`v_firstQ` 트래킹 픽셀이 특정 매체/SSP에서 누락되거나 실패하고 있을 가능성**이 큽니다. 어느 `media_id`/`ctv_media`에서 집중 발생하는지 세분화 확인을 권장합니다.

---

## 🟡 확인이 권장되는 발견

### 4. B2 — postback_log 중복 이벤트 (LIMIT 100까지 모두 채워짐 → 실제로는 100건 이상 존재)
동일 `req_id + log_type + created_at` 조합이 2번씩 적재된 행이 최소 100건 발견되었습니다. 특이하게도 그중 99건이 **정확히 동일한 타임스탬프 `2026-06-02T23:41:13`** 에 몰려 있고(`v_mid`, `v_firstQ`, `v_progress`, `v_start` 등 여러 log_type에 걸쳐 발생), 나머지 1건만 `2026-06-07T12:07:25`(log_type `i`)입니다.
→ **2026-06-02T23:41:13 시점에 배치 재처리(reprocessing)나 파이프라인 재시도로 인한 대량 중복 적재**가 있었던 것으로 추정됩니다. `LIMIT 100`이 결과를 잘랐으므로, 정확한 총 중복 건수 파악을 위해 `LIMIT` 없이 재실행하거나 `count(*)`로 총량을 확인하는 것을 권장합니다.

### 5. C3 — bid_log_flatten ↔ postback_log `cmp_no` 불일치 (1건)
기간 내 `bid_log_flatten`의 distinct `cmp_no` = 7건, `postback_log`의 distinct `cmp_no` = 8건, 교집합 = 7건. **postback에는 있는데 bid 로그에는 없는 `cmp_no`가 1건** 존재합니다. (참고: 이전 10건 샘플 데이터로는 두 테이블의 cmp_no가 전혀 안 겹치는 것처럼 보였으나, 실제 7일치 데이터로는 87.5%가 정상적으로 겹칩니다 — 두 로그가 같은 캠페인 ID 체계를 공유하는 것으로 확인됨.)

### 6. F1 — 06-03 postback 건수 급감
| 일자 | bid_req_cnt | postback_req_cnt | postback/bid 비율 |
|---|---:|---:|---:|
| 06-01 | 12,377,097 | 18,196 | 0.147% |
| 06-02 | 13,105,323 | 15,539 | 0.119% |
| **06-03** | **14,178,702** | **5,927** | **0.042%** |
| 06-04 | 11,601,827 | 17,163 | 0.148% |
| 06-05 | 12,337,772 | 15,668 | 0.127% |
| 06-06 | 13,227,279 | 23,083 | 0.174% |
| 06-07 | 13,088,421 | 25,334 | 0.194% |

06-03은 bid 요청량이 7일 중 가장 많았음에도 postback(전환) 건수는 최저치(다른 날 대비 약 1/3 수준)입니다. 정상적인 상관관계(요청↑ → 전환↑)와 반대 방향이라 **해당 일자 포스트백 수집 파이프라인 장애 가능성**을 의심해볼 필요가 있습니다.

### 7. F2 — postback이 전혀 없는 media_id (2건)
`Y2AXA67DZOMW`, `F4MZ8QK1A9X2` 두 매체는 기간 내 bid 로그에는 존재하지만 postback 로그에는 한 번도 나타나지 않았습니다. 신규/저볼륨 매체라 전환이 우연히 없었을 수도 있고, 해당 매체에 포스트백 픽셀 연동이 안 되어 있을 수도 있습니다 — 매체 담당자 확인 권장.

### 8. D7 — device_ifa 비표준 값 (8건, 참고용)
UUID 형식이 아닌 `device_ifa` 값들이 발견되었습니다: `{PSID}`(6건), `test_channelA_new`, `test_sentv`. `{PSID}`는 macro가 치환되지 않은 placeholder로 보이며, `test_*` 값은 테스트 트래픽으로 추정됩니다. 집계/타겟팅 로직에서 이런 값들이 실 사용자로 오인되지 않도록 필터링이 필요할 수 있습니다. (기간 내 전체 대비 8건이라 비중은 미미합니다.)

### 9. C2 — advertisement에서 참조되지 않는 business (20/45건, 44%)
전체 45개 사업자 중 20개는 현재 어떤 광고에도 연결되어 있지 않습니다. 오류라기보다는 **광고 집행 전 등록만 된 사업자**일 가능성이 높아 참고 정보로만 남깁니다.

---

## 🟢 정상 확인된 항목

| 검증 | 결과 |
|---|---|
| A1 | bid_log: `req_id`/`media_id` 결측 0건. `price/cmp_no/ag_no/deal_id` 결측 99.66%(낙찰 미발생 요청으로 추정, 오류 아님) |
| A2 | postback_log: 핵심 컬럼(`req_id/log_type/cmp_no/ag_no/price/ifa`) 결측 0건 |
| A3 | advertisement: 핵심 컬럼 결측 0건 |
| A4 | business: 핵심 컬럼 결측 0건 |
| B1 | bid_log `(req_id, imp_id)` PK 중복 **0건** |
| B3 | advertisement `adspid` PK 중복 **0건** |
| B4 | business `businessid` PK 중복 **0건** |
| B5 | business `businessnum` 중복 등록 **0건** |
| C1 | advertisement → business FK 위반(고아 레코드) **0건** |
| C5 | bid_log `imp_deals_array` 내부 `id`와 `deal_id` 컬럼 불일치 **0건** |
| D1 | advertisement `usefg` 도메인(Y/N) 위반 **0건** |
| D2 | advertisement `onoff` 도메인(0/1) 위반 **0건** |
| D4 | bid_log `price` 음수/`bidfloor` 미만 낙찰 **0건** |
| D5 | postback_log `price`/`base_price` 음수 **0건** |
| E1 | bid_log `year/month/day/hour` vs `created_at` 불일치 **0건** |
| E2 | postback_log `year/month/day/hour` vs `created_at` 불일치 **0건** |

---

## 후속 조치 제안

1. **C4 재실행** — postback에는 있는데 bid_log에 없는 `deal_id` 목록 확인 (이번 라운드 미실행).
2. **B2 전체 건수 확인** — `LIMIT 100` 제거 후 `2026-06-02T23:41:13` 중복 적재의 정확한 규모와 원인(재처리 배치/재시도) 파악.
3. **D8 퍼널 역전 세분화** — `v_firstQ` 누락을 `media_id`/`ctv_media`/`app_bundle` 기준으로 쪼개서 특정 매체 이슈인지 확인.
4. **F1 06-03 원인 조사** — 포스트백 수집 파이프라인/로그 적재 히스토리 확인.
5. **D3, D6 원본 데이터 수정** — 캠페인 `adspid=10028` 날짜, 사업자 `businessid=109` 사업자번호.
