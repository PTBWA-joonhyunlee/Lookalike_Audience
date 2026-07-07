# 관심 사용자 리스트 프로젝트 - 확인 쿼리 (정리됨)

특정 광고(cmp_no) 관심 사용자 리스트(`querys/audience_list_extraction/`)와 임베딩 파이프라인
(`querys/audience_embedding/`)을 설계하기 위해 거쳐간 확인 쿼리들. 결론에 계속 쓰이는 쿼리만
여기 남기고, 결론은 났지만(가설 기각/매핑 없음 확인 등) 재실행할 일이 없는 쿼리는
`_archived/`로 옮겼다 — 각 쿼리가 낸 결론은 아래 표와 `docs/audience_list_project.md`에 남아있다.

## 현재 남은 쿼리와 용도

| 파일 | 확인 목적 | 결론 → 반영된 곳 |
|---|---|---|
| G4 | `bid_log_flatten.device_ifa` ↔ `postback_log.ifa` 동일 식별자인지 | 100% 오버랩 확인 → J1/J2 조인 키로 사용 |
| G5 | 동의/옵트아웃(`req_ext_allow_user_data_collection`, `device_lmt`) 채움률 | 실제 채워짐 확인 → 컴플라이언스 필터 근거 |
| G6 | placeholder 디바이스ID(`{PSID}`, `test_*`, all-zero) 스캔 | 극소량 확인 → J1/J2의 UUID 정규식 필터 근거 |
| G7 | 캠페인(cmp_no/ag_no)별 노출/참여 볼륨 | cmp_no=10115 등 파일럿 캠페인 선정 근거, `docs/audience_list_project.md` 파일럿 결과 비교 기준 |
| H6 | `req_ext_allow_user_data_collection` 값 분포 | `'1'`=93%/`'0'`=3%/NULL=4% 확인 → "NULL 제외 유지" 정책 근거 |
| H7 | `req_user_id` ↔ `device_ifa` 관계(1:1/1:N), 값 포맷 | 거의 1:1 확인 → req_user_id를 보조 식별자로 채택, 임베딩에서도 그대로 사용 |
| K1 | "완료(T4)" 유저가 컴플라이언스 필터에서 유독 탈락하는 이유 진단 | `tv.anypoint.skb` 매체의 동의 필드 100% 미채움 확인 → 사용자 확인 후 보수적 제외 유지 결정 |
| L1 | `abi_bid_log_flatten` 스키마/샘플 확인 | addi와 컬럼 구조가 거의 동일함을 확인 → `querys/audience_embedding/`에서 `user-to-ad-encoder` 코드 재사용 근거 |

## `_archived/` — 결론은 유효하지만 재사용 안 하는 쿼리

| 파일 | 확인했던 것 | 결론 (반영된 곳) |
|---|---|---|
| G1, G2 | `ptbwa-metadata`/`prod-ptbwa-dw`의 전체 테이블 목록 | `adcampaign`/`adgroup`/`adcreative`/`addi_advertisement2`/`user`/`abi_bid_log_flatten` 등 발견 → 아래 항목들의 출발점. 목록 자체는 일회성 조회라 재실행 불필요 |
| G3 | `postback_log.g_targetid`/`deal_id` ↔ `advertisement.targetbillingid`/`targetdealnogab` 브릿지 가설 | JOIN fan-out + 좁은 커버리지로 신뢰 불가 판정, 이후 H/I에서 다른 방식으로 최종 기각 |
| G8 | `req_user_id` 채움률 | H7이 관계/포맷까지 포함해 더 상세히 재확인 — 중복이라 G8은 제거 |
| H1-H4 | `adcampaign`/`adgroup`/`adcreative`/`addi_advertisement2` 구조 및 cmp_no/ag_no 매핑 후보 여부 | I1-I3에서 ID 범위 자체가 다름(우리 cmp_no 10000+대 vs 이 테이블들 143-417/260-1971대) 확인 → **매핑 없음, cmp_no를 광고 식별자로 직접 사용** (`docs/audience_list_project.md` 확정 결정 1행) |
| H5 | `user` 테이블 구조 (개인정보 여부) | 내부 운영자/관리자 계정(77건)으로 확인, 일반 소비자 PII 아님 → 오디언스 프로젝트 범위에서 제외 |
| I1-I3 | cmp_no/ag_no가 adcampaign/adgroup에 실제 존재하는지, billing-id 브릿지 재검증 | 값 범위 불일치로 매핑 없음 최종 확인 (H1-H4 결론과 동일 근거) |
| L2, L3 | `req_user_id`/`device_ifa` 기준 addi↔abi 오버랩 | req_user_id 오버랩 0%, device_ifa 오버랩 16% 확인했으나, 사용자가 "abi 연계는 고려하지 않음"으로 결정 → 폐기된 방향. L1의 스키마 동일성 확인만 남기고 이 두 쿼리는 보관용으로 이동 |

## 관련 문서
- 최종 설계 결정: [`docs/audience_list_project.md`](../../docs/audience_list_project.md)
- 임베딩 설계/학습 계획: [`docs/audience_embedding_plan.md`](../../docs/audience_embedding_plan.md)
