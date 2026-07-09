# ADDI 데이터 스키마 문서

`sample_data/` CSV 샘플(각 10건) 및 Athena 검증 쿼리 실행 결과(`sample_data/valiation/`, 2026-06-01~06-07 기준)를 바탕으로 정리했습니다.

## 테이블 개요

| 테이블 | 성격 | Grain(행 단위) | 기간 내 행 수(2026-06-01~07) |
|---|---|---|---|
| `prod-ptbwa-dw.addi_bid_log_flatten` | RTB 입찰 로그 | 요청 1건의 impression 단위 (`req_id`+`imp_id`) | 89,916,421 |
| `prod-ptbwa-dw.addi_postback_log` | 광고 이벤트(포스트백) 로그 | 이벤트 1건 (`req_id`+`log_type`) | 812,835 |
| `ptbwa-metadata.addi_advertisement` | 광고(캠페인) 마스터 | 광고 1건 (`adspid`) | 180 (스냅샷) |
| `ptbwa-metadata.addi_business` | 사업자(광고주) 마스터 | 사업자 1건 (`businessid`) | 45 (스냅샷) |

두 로그 테이블은 `year/month/day/hour` 파티션 컬럼을 가지며, 실측 결과 해당 컬럼은 `created_at`(ISO8601)과 100% 일치합니다(E1, E2 검증 결과 0건 불일치).

---

## 1. `addi_bid_log_flatten` (83 컬럼)

RTB(OpenRTB 계열) 입찰 요청/응답을 플랫하게 펼친 로그. 컬럼 그룹:

- **요청 식별/타이밍**: `req_id`, `req_at`, `req_tmax`, `created_at`, `year/month/day/hour`
- **Impression/비디오 스펙**: `imp_id`, `imp_video_*`(mimes, linearity, maxduration, w/h, startdelay), `imp_tagid`, `imp_bidfloor(cur)`, `imp_deals_array`, `imp_ad_type`, `imp_secure`
  - `imp_deals_array`는 문자열이 아니라 **`array(row(id varchar, bidfloorcur varchar, bidfloor double))`** 실제 구조체 배열 타입 (CSV 상 `[{id=..., bidfloorcur=..., bidfloor=...}]` 형태로 보이지만 Athena 테이블에서는 파싱된 배열/구조체).
- **앱/디바이스**: `app_bundle`, `device_ua`, `device_ip`, `device_geo_country`, `device_geo_zip`, `device_os`, `device_devicetype`, `device_ifa`(광고식별자, 표준 형태는 UUID)
- **낙찰 결과**: `res_id`, `price`, `crtv_no`, `crid`, `cmp_no`(캠페인), `ag_no`(광고그룹), `deal_id`, `impid`

### 컬럼 타입 주의사항 (Athena 실제 타입)
Glue 크롤러가 숫자처럼 보이는 값을 `double`/`bigint`로 추론해 둔 컬럼이 존재합니다. 문자열 함수(`trim`, `regexp_like`, `LIKE`, `||`)를 쓸 때는 반드시 `CAST(col AS VARCHAR)`로 감싸야 합니다. 예: `price`, `cmp_no`, `ag_no`, `deal_id`, `businessid`, `onoff`, `businessnum` 등.

### 결측 패턴 (A1 결과, n=89,916,421)
| 컬럼 | NULL 건수 | 비율 |
|---|---|---|
| `req_id` | 0 | 0% |
| `media_id` | 0 | 0% |
| `price` / `cmp_no` / `ag_no` / `deal_id` | 89,607,353 | **99.66%** |
| `device_ifa` | 4,227,313 | 4.70% |

`price/cmp_no/ag_no/deal_id`가 4개 컬럼 모두 정확히 같은 건수로 NULL인 것으로 보아, 이 4개 컬럼은 **낙찰(win)이 발생한 요청에만 채워지는 필드**로 보입니다. 즉 전체 입찰 요청의 약 0.34%(≈309,068건)만 낙찰까지 이어졌습니다. `device_ifa` 결측(4.7%)은 IFA를 주지 않는 디바이스/트래픽(CTV 일부, 옵트아웃 등)으로 추정됩니다.

---

## 2. `addi_postback_log` (43 컬럼)

비디오 재생 등 광고 이벤트 트래킹(포스트백) 로그. 컬럼 그룹:

- **이벤트 식별**: `log_t`(고정값 `postback`), `log_type`, `req_id`, `ifa`
- **캠페인/매체 매핑**: `tag_id`, `media_id`, `cmp_no`, `ag_no`, `creative_no`, `deal_id`, `app_id/app_bundle`, `ctv_media`, `content_id`
- **가격/정산**: `price`, `price_encrypt`, `d_p`, `is_cpvc`, `uplift_rate`, `base_price`
- **위치/네트워크**: `area_cd`, `zipcode`, `region`, `ip`, `request_ip`
- **지연/에러 진단**: `url_genarate_ts`, `url_genarate_d_min`, `error_msg`

### `log_type` 분포 (D8 결과, n=812,835 이벤트 / 120,910 distinct req_id 추정)
| log_type | 건수 | 비고 |
|---|---:|---|
| `i` (impression) | 120,848 | 퍼널 시작점 |
| `v_start` | 120,755 | |
| `v_progress` | 120,301 | |
| `v_thirdQ` | 119,010 | 75% 지점 |
| `v_mid` | 113,198 | 50% 지점 |
| `v_complete` | 109,931 | 100% 완료 |
| `v_firstQ` | 108,729 | 25% 지점 — **비정상적으로 낮음, 아래 검증 리포트 참고** |
| `e_v_start`, `e_i`, `e_v_firstQ`, `e_v_progress`, `e_v_complete`, `e_v_thirdQ`, `e_v_mid` | 각 7~14 | `e_` 접두사: 지연/에러 처리된 이벤트(예: "Event occurred over 60 minutes after ad served") |

결측률(A2 결과)은 `req_id/log_type/cmp_no/ag_no/price/ifa` 전부 0% — 이 테이블은 핵심 컬럼 기준 매우 깨끗합니다.

---

## 3. `addi_advertisement` (80 컬럼)

광고(캠페인) 마스터. 스냅샷 성격이라 기간 필터를 적용하지 않았으며, 조회 시점 기준 총 180건.

- **기본정보**: `adspid`(PK), `adsnm`, `businesstype`, `startdt/enddt`, `status`, `onoff`, `usefg`
- **타겟팅**: `timetarget(array)`, `usertarget(array)`, `mediatargettype/channel/category`
- **예산**: `budgetperiodtype`, `goalbudgetplan/confirmed`, `goalbudget`, `dailybudget`
- **소재**: `format`, `width/height/duration/bitrate`, `mediapath`, `youtubeurl`, `brandlogofilename/path`
- **정산/보증**: `guaranteecpvc(gab/apm)`, `targetdealno*`, `targetbillingid`, `fee_rate`, `settlementstatus`
- **감사/이력**: `auditno`, `regdt/reguserid`, `moddt/moduserid`, `reason`
- **FK**: `businessid` → `addi_business.businessid`

핵심 컬럼(`adspid`, `businessid`, `startdt`, `enddt`, `status`) 결측 0% (A3). `usefg`는 Y/N만, `onoff`는 0/1만 존재(D1, D2) — 도메인 값 정상.

---

## 4. `addi_business` (20 컬럼, 원본 테이블명 오타 `addi_bisiness` → `addi_business`로 정정)

사업자(광고주) 마스터. 조회 시점 기준 총 45건.

- **사업자 정보**: `businessid`(PK), `businessnum`(사업자등록번호), `businessnm`, `businessaddress`, `businesstype/item`, `ceonm`
- **정산계좌**: `refundaccountbank/number/holder/regdt`, `refundaccountcheckfg`
- **상태/이력**: `usefg`, `businesscheckfg`, `reguserid/regdt`, `moddt`, `openingdt`

핵심 컬럼(`businessid`, `businessnum`, `businessnm`) 결측 0% (A4).

---

## 테이블 관계

```
addi_business.businessid ──< addi_advertisement.businessid   (FK 정상, 고아 레코드 0건)
addi_bid_log_flatten ──(cmp_no, deal_id, media_id)── addi_postback_log   (기간 내 cmp_no 7/8건 교차, 아래 리포트 참고)
```

`addi_advertisement.adspid`와 로그 테이블의 `cmp_no`/`ag_no`는 값 체계가 달라(예: adspid=573 vs cmp_no=10053) 직접 조인되지 않습니다. 캠페인/광고그룹 마스터가 별도로 존재할 가능성이 높습니다 — 확인 필요.

정합성 검증 세부 결과는 [`_archive/data_validation_report.md`](_archive/data_validation_report.md) 참고.

이 문서는 원본(raw) Athena 테이블 스키마를 다룬다. `querys/audience_embedding/`의 SQL이
뽑아내는 가공된 산출물(파이프라인 입력 CSV) 스키마는 [`audience_embedding_data_schema.md`](audience_embedding_data_schema.md)
참고.
