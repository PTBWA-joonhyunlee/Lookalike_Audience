# 규칙 기반 관심 사용자 리스트 (J1/J2)

임베딩 없이 bid+postback 로그만으로 특정 광고(`cmp_no`)에 이미 반응한 유저를 뽑는 트랙.
실행 방법은 [`README.md`](../README.md) §6, 전체 조사 과정/의사결정 히스토리는
[`_archive/audience_list_project_full.md`](_archive/audience_list_project_full.md) 참고.

## 확정된 설계 결정

| 항목 | 결정 | 근거 |
|---|---|---|
| 광고 식별자 | `cmp_no`(+`ag_no`) 사용, `adspid` 미사용 | 둘 사이 매핑 없음(전수 조사로 확인) |
| 유저 식별자 | `device_ifa`(=`postback_log.ifa`, 100% 동일) 기본 키, `req_user_id` 보조 키 | |
| 컴플라이언스 필터 | `req_ext_allow_user_data_collection='1'`만 포함(NULL 제외), `device_lmt='1'` 제외 | 보수적 정책, 확정됨 |
| 디바이스ID 정제 | UUID 형식(`^[0-9a-fA-F-]{36}$`)만 포함 | placeholder 값 제외 |
| 관심도 티어 | T1 노출만 / T2 참여시작(`i`,`v_start`) / T3 중간참여(`v_mid`+) / T4 고관여·완료(`v_complete`) | |
| 참여 강도 지표 | `count(DISTINCT log_type)` 사용, `count(*)` 금지 | 중복 적재 로그로 인한 왜곡 방지 |

## 쿼리

- `querys/audience_list_extraction/J1_audience_tier_full.sql` — 대상 캠페인 전체 노출자 + 티어 분포(T1 포함)
- `querys/audience_list_extraction/J2_interested_users_final.sql` — 최종 리스트(T2 이상만)

둘 다 상단의 `cmp_no` 값을 원하는 캠페인 번호로 교체해서 재사용.

## 파일럿 결과 (cmp_no=10115, 2026-06-01~06-07)

| 티어 | 인원 | 비율 |
|---|---:|---:|
| 전체 대상자(컴플라이언스 필터 통과) | 38,557 | 100% |
| T1 노출만 | 29,424 | 76.3% |
| T2 참여시작 | 52 | 0.13% |
| T3 중간참여 | 1,827 | 4.7% |
| T4 고관여(완료) | 7,254 | 18.8% |
| **최종 리스트(J2, T2 이상)** | **9,133** | **23.7%** |

산출물: `data/audience_list_extraction/J1_audience_tier_full_cmp10115.csv`,
`J2_interested_users_final_cmp10115.csv`.

동의 필터 적용 전 이 캠페인의 완료자는 14,766명이었으나, 특정 매체(`tv.anypoint.skb`)의
동의 필드가 100% 미채움이라 9,934명이 제외되어 최종 7,254명만 남음 — 매체 연동 이슈로
추정되지만 리스크 회피를 위해 보수적으로 제외 유지하기로 확정(사용자 결정).
