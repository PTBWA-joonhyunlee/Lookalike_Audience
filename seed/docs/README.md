# seed 트랙 — 피엘라벤 seed 기반 신규 유저 룩어라이크

`피엘라벤_seed.csv`(외부 CRM/3rd-party 소스, device_ifa 1,518,101명(정제 후) — 이 프로젝트
로그 테이블과 무관하게 확보된 리스트, `ab_postback_log`로 재현/검증 불가, 2026-07-29 확인)를
seed로 두고, propfit 소스(`abi_bid_log_flatten` bid log + `propfit.skp` 세그먼트)에서
비슷한 신규 유저를 찾는 트랙. `seed/queries/lib/`의 3개 쿼리(01/02/11)를 피처 추출
라이브러리로 재사용하고, `seed/queries/`는 seed 전용 조인/스코어링 대상 쿼리를 담는다.

**"신규" 정의(2026-07-29 확정)**: postback 이력과 무관하게, seed 리스트에 없는 bid log
유저는 전부 신규 후보로 본다. `ab_postback_log`는 지금 단계에선 쓰지 않고, 추후 실제
캠페인이 집행되면 후보 리스트의 전환 여부를 확인하는 백테스트 라벨 소스로만 남겨둔다.

이 문서는 "지금 어떻게 실행하고 뭐가 나오는지" 위주다. 조사 과정(ID 공간 크로스워크 발견,
표본 버그 두 건 등)은 `eda/docs/`에 별도로 있다.

## 실행 순서

`seed/queries/lib/01,02,11`을 기반으로 아래 순서대로 실행한다(Athena 콘솔, 이 repo는
Athena 접근 권한 없음). 괄호 안은 재편 전 파일명(과거 대화/커밋 참고용).

| # | 쿼리 | 역할 | 상태 |
|---|---|---|---|
| 01 | `01_create_seed_table.sql` (구 `00_create_seed_table.sql`) | seed CSV를 S3 업로드 후 Athena 외부 테이블(`seed_piellaven`)로 등록 | 완료 |
| 02 | `02_create_seed_ad_id_table.sql` (구 `03_...`) | seed → skb 크로스워크 결과를 `seed_piellaven_ad_id` 테이블로 materialize(GAID 공간) | 완료 |
| 03 | `03_create_media_vocab_table.sql` (구 `04_...`) | media top500 vocab을 전체 모집단 기준으로 한 번만 만들어 `propfit_media_top500`로 공유 | 완료 |
| 04a | `04a_seed_profile.sql` (구 `05a_...`) | lib/01 + `seed_piellaven_ad_id` 조인, 전수 | 완료 — 1,197,069행 |
| 04b | `04b_seed_media.sql` (구 `05b_...`) | lib/02 + `seed_piellaven_ad_id` 조인 + vocab 참조, 전수 | 완료 — 25,987,971행 / 1,015,872명 |
| 04c | `04c_seed_segment.sql` (구 `05c_...`) | lib/11 + `seed_piellaven_ad_id` 조인, 전수 | 완료 — 2,496,351행 |
| 05a | `05a_pool_profile.sql` (구 `06a_...`) | lib/01 + seed 제외 + 5% 표본(device_ifa 해시, crc32), 2026-04~05 | 완료 — 350만 행 안팎(재실행 필요, 아래 참고) |
| 05b | `05b_pool_media.sql` (구 `06b_...`) | lib/02 + seed 제외 + 05a와 동일 표본 키 + vocab 참조 | 완료 |
| 05c | `05c_pool_segment.sql` (구 `06c_...`) | lib/11 + seed 제외 + 05a와 동일 표본 키 | 완료 |
| 06 | `06_create_candidate_table.sql` (구 `07_...`) | "신규 후보"(seed 제외 + 2026-06 활동 + skp 세그먼트 매칭) device_ifa를 `candidates_202606` 테이블로 materialize | 완료 |
| 07a | `07a_candidate_profile.sql` (구 `08a_...`) | lib/01 + `candidates_202606` 조인, 2026-06, 전수 | 완료 — 843만 행 규모(세그먼트 매칭 기준으로 재정의 후 재실행 필요, 아래 참고) |
| 07b | `07b_candidate_media.sql` (구 `08b_...`) | lib/02 + `candidates_202606` 조인 + vocab 참조 | 완료 |
| 07c | `07c_candidate_segment.sql` (구 `08c_...`) | lib/11 + `candidates_202606` 조인 | 완료 |

## 설계 결정 요약

- **media vocab 공유**: `lib/02_user_media.sql`은 top500 미디어를 조회 대상 population
  안에서 자체 계산한다 — seed/pool/후보가 각각 따로 계산하면 vocab이 달라져 embedding
  모델이 한쪽 데이터를 대거 OOV로 취급하게 된다. 그래서 `03_create_media_vocab_table.sql`로
  top500을 전체 모집단 기준 한 번만 계산해 `propfit_media_top500` 테이블로 고정하고,
  seed/pool/후보 전부 이 테이블을 참조한다(자체 재계산 안 함).
- **신규 후보 기간**: 학습(pool/seed) 기간은 2026-04~05, 후보는 이와 겹치지 않는
  **2026-06**로 잡았다(addi 트랙의 학습/스코어링 기간 분리 관례와 동일) — "seed에 없으면
  신규"를 기간 제한 없이 적용하면 약 7,000만 명(media 이벤트 기준 수백 GB)이 되어 실행이
  불가능하기 때문.
- **후보 정의 = seed 제외 + 2026-06 활동 + skp 세그먼트 매칭**: 처음엔 규모 문제로 20%
  무작위 표본을 썼는데, 그 결과 세그먼트 매칭이 후보의 1.6%뿐이라 나머지는
  segment_features가 전혀 없는 상태가 됐다(원인 조사는 `eda/docs/sampling_bugs.md` 참고 —
  버그 아니고 신규 후보 모집단의 실제 특성으로 결론). 그래서 무작위 표본 대신 **skp
  세그먼트 매칭 여부**를 후보 정의 조건에 넣었다 — 규모도 자연스럽게 줄고(추정 66만 명
  안팎) 후보 전원이 profile+media+segment 3개 피처를 다 갖게 된다. 트레이드오프: DMP에
  전혀 안 잡히는(세그먼트 태깅 이력 없는) 유저는 후보에서 빠진다.
- **pool 표본 5%**: seed(양성, 04a 전수 1,197,069행) 대비 pool(음성)이 너무 적으면
  지도학습에 불리해 0.5%→5%로 올렸다.
- **재실행 필요 항목**: 위 표의 "재실행 필요" 표시된 행 — 05a/05b/05c는 표본 버그
  수정(`eda/docs/sampling_bugs.md` 참고) 후 5% 표본으로, 06/07a/07b/07c는 후보 정의를
  세그먼트 매칭 기준으로 바꾼 뒤로 다시 실행해야 최신 결과다.

## 데이터 정제 메모

원본 `피엘라벤_seed.csv`(로컬 `data/seed/00_피엘라벤_seed.csv`) 1,518,104행 중 3행이 UUID
형식이 아니었다 — `[DEVICE_ADI`, `{PSID}`, `platform_ad_id` (여러 추출 배치를 이어붙이며
남은 헤더 파편으로 추정). 로컬에서 제거 완료(1,518,101행, 정제 검증 후 원본 백업은
삭제됨) — S3에는 이 정제된 버전을 올릴 것.

## Athena 파싱 에러 메모

`CREATE TABLE ...;` 실행 시 `ParseException ... cannot recognize input near '<EOF>'`가 난
적이 있다 — 원인은 실행 과정에서 줄바꿈이 사라지면서(콘솔 붙여넣기/스크립트 실행 방식에
따라 발생 가능) `--` 줄 주석이 개행으로 안 끊기고 뒤의 SQL 문 전체를 삼켜버린 것. 그래서
이 트랙의 모든 쿼리는 `--` 대신 개행에 의존하지 않는 `/* */` 블록 주석을 쓴다. 또한
Athena는 쿼리 하나당 statement 하나만 허용하므로, 진단용으로 여러 SELECT를 한 파일에
세미콜론으로 나눠 쓰지 않는다(파일을 쪼갠다).

## 다음 단계

파이썬 쪽(임베딩 모델) 작업은 `../README.md`(seed 트랙 진입점)와 `model_architecture.md`
참고 — profile/media 임베딩 모델이 아직 없고, segment_features는 학습 스크립트까지만
있고 추론 스크립트가 없다.
