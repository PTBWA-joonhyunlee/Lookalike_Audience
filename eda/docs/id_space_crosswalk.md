# ID 공간 크로스워크 조사 (2026-07-29)

`seed/queries/04c_seed_segment.sql`(당시 `01_seed_coverage_check.sql`로 직접 조인) 결과,
피엘라벤 seed(150만 device_ifa)가 `abi_bid_log_flatten.device_ifa`와는 8.9% 매칭됐지만
`propfit.skp.ad_id`(세그먼트)와는 0.0%(1명)만 매칭됐다 — 이 격차의 원인을 추적한 기록.
관련 쿼리: `eda/queries/09~18`.

## 1차: 01/10/11 결과 — 이상 발견

| seed_total | seed_in_bidlog | seed_in_segments | pct_in_bidlog | pct_in_segments |
|---|---|---|---|---|
| 1,518,101 | 135,165 | 1 | 8.9% | 0.0% |

`eda/queries/09_seed_coverage_check.sql` 결과. bidlog 매칭(8.9%, 13.5만 명)은 학습
표본으로 쓸 만한 규모지만, segment 매칭이 1명뿐인 건 통계적으로 이상하다 — skp가
distinct ad_id ~5,330만 건을 갖는데, 실제 GAID임이 확실한(bidlog와 13.5만 건 우연히
겹칠 확률은 사실상 0) 150만 명 리스트와 겹침이 1건이라는 건 skp가 진짜 5,330만 개의
raw GAID를 담고 있다면 통계적으로 불가능하다.

두 가설을 세우고 각각 기각했다:
- **가설 A(iOS 편중)**: `eda/queries/10_seed_bidlog_os_check.sql` — seed∩bidlog(135,165명)의
  device_os 분포가 **100% android**로 나와 기각(iOS가 원인이면 오히려 skp 커버리지가
  더 좋아야 함).
- **가설 B(id_type 필터 오류)**: `eda/queries/11_seed_skp_id_type_check.sql` — id_type
  필터를 풀어도 매칭은 여전히 `id_type='2'`, 1건뿐 — 기각.

`00_id_mapping_check.sql`(2026-07-24, `eda/queries/00_id_mapping_check.sql`)의
"`skp.ad_id` = `device_ifa` 공간" 결론은 매칭 건수(fan-out 포함)로 추론한 것이지 값
포맷을 직접 검증한 게 아니었다 — 재검증이 필요했다.

## 2차: 크로스워크 확인 — 결정적 발견

`eda/queries/12_seed_skb_crosswalk_check.sql`로 seed를 `propfit.ptbwa_skb`의 세 컬럼
(`ad_id`/`platform_ad_id`/`uuid`) 각각과 직접 대조:

| seed_total | seed↔skb.ad_id | seed↔skb.platform_ad_id | seed↔skb.uuid |
|---|---|---|---|
| 1,518,101 | 0 | **928,809 (61.2%)** | 87,542 (5.8%) |

seed는 raw GAID(`ad_id`) 공간이 아니라 **`platform_ad_id` 공간**에 있었다 — 이는
`00_id_mapping_check.sql`에서 `ptbwa_tg.uuid`가 살던 바로 그 공간과 같다. 한편
`eda/queries/13_skp_ad_id_format_census.sql`/`14_skp_ad_id_sample.sql`로 확인한 결과
`skp.ad_id`는 실제로 거의 다 정상 UUID 형식이다(길이 36인 53,511,543건 중 53,511,539건이
UUID 정규식 통과) — skp 쪽 데이터 자체엔 문제가 없고, **seed의 ID 공간이 skp/skb.ad_id와
애초에 다른 공간이었던 것**이 0.0% 매칭의 진짜 원인이었다.

(참고: `eda/queries/15_bidlog_device_ifa_format_census.sql`은 `abi_bid_log_flatten.device_ifa`
자체가 raw GAID와 다른 형식 ID가 섞인 컬럼일 가능성을 확인하려던 것 — 이후 06(샘플링
버그) 조사에서 직접적인 원인은 아닌 것으로 정리됨, `sampling_bugs.md` 참고.)

## 3차: 크로스워크 적용 — fan-out으로 1차 왜곡, 재집계로 확정

seed → `skb.platform_ad_id` → `skb.ad_id`로 한 번 크로스워크하면 진짜 GAID를 얻어
bidlog/skp 양쪽에 다시 붙일 수 있다는 가설로 `eda/queries/16_seed_crosswalk_bidlog_check.sql`
/`17_seed_crosswalk_segment_check.sql`을 실행했더니:

| seed_total | seed_crosswalked_to_ad_id | crosswalked_matches_bidlog | crosswalked_matches_segments |
|---|---|---|---|
| 1,518,101 | 2,519,634 | 1,197,069 | 2,496,351 |

`seed_crosswalked_to_ad_id`(2,519,634)가 `seed_total`(1,518,101)보다 컸다 —
`ptbwa_skb`에서 `platform_ad_id` 하나가 여러 `ad_id`로 매핑되는 fan-out(1:N)이 있다는
뜻이라, 이 숫자들은 "distinct ad_id 개수" 기준이라 실제 seed 커버리지로 해석할 수
없었다(부풀려짐). `eda/queries/18_seed_crosswalk_check_deduped.sql`로 "distinct seed
유저" 기준으로 다시 집계:

| seed_total | crosswalk 있음 | → bidlog 매칭 | → segment 매칭 |
|---|---|---|---|
| 1,518,101 | 928,809 (61.2%) | 772,768 (50.9%) | 926,410 (61.0%, crosswalk 대비 99.7%) |

직접 조인 대비(8.9%/0.0%) 압도적으로 개선됐다 — 특히 segment는 크로스워크된 유저 거의
전원(99.7%)이 커버돼 **`segment_features`를 이번 트랙에 포함할 수 있다**는 결론을 내렸다.

## 최종 설계 반영

seed의 device_ifa는 항상 `skb.platform_ad_id → skb.ad_id` 크로스워크를 거쳐 얻은 진짜
GAID를 키로 쓴다 — 이 GAID 집합이 이후 모든 seed 피처 추출과 "신규 후보(pool − seed)"
판정의 기준이다. `seed/queries/02_create_seed_ad_id_table.sql`(구 `03_...`)이 이 크로스워크
결과를 `seed_piellaven_ad_id` 테이블로 한 번 materialize해서 재사용한다.
