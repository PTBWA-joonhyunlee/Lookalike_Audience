/* ============================================================
   segment/03_create_candidate_table.sql (seed, 2026-08-04 segment/media 트랙 분리 — 구
   06_create_candidate_table.sql)
   목적: "신규 후보"(2026-07-30 확정 — seed 리스트에 없음 + 2026-06 최근 활동 + skp
   세그먼트 매칭) device_ifa 목록을 만든다 — segment 트랙 전용(candidates_202606). 학습
   기간(pool/seed = 2026-04~05)과 겹치지 않는 06월로 잡아 학습/스코어링 기간 분리 관례를
   따른다.

   segment/04_candidate_segment.sql이 이 테이블을 device_ifa 키로 참조한다.

   2026-07-30 수정(UUID 필터): device_ifa UUID 형식 필터를 추가했다 — seed는
   skb.ad_id 크로스워크를 거쳐 이미 UUID 공간이므로(02d/02e 확인), 후보도 같은 ID
   공간으로 맞추기 위함.

   2026-07-30 수정(20%→segment 매칭 기준으로 교체): 처음엔 규모 문제(필터 없이 08a가
   4,000만 행) 때문에 20% 무작위 표본을 썼는데, 그 결과 08c(세그먼트)가 후보의
   1.6%에서만 매칭돼 나머지 98.4%는 segment_features가 전혀 없는 상태가 됐다(대소문자
   문제 아님 — 09b_candidate_segment_case_check.sql로 기각 확인됨, 신규 후보 모집단의
   실제 특성). 사용자 요청으로 무작위 표본 대신 **skp 세그먼트 매칭 여부 자체를 후보
   정의 조건으로 바꿨다** — 규모도 자연스럽게 줄고(추정 66만 명 안팎, 132,897÷20%),
   후보 전원이 profile+media+segment 3개 피처를 다 갖게 된다. 대신 "DMP에 전혀 안
   잡히는(태깅 이력 없는) 완전 미지의 유저"는 후보에서 빠진다는 트레이드오프가 있다
   (설계상 허용 — "신규"의 정의는 여전히 "seed에 없음"이고, 이건 그중 스코어링
   가능한 하위집합을 고르는 추가 조건일 뿐).

   **재실행 필요**: 07(이 파일), 08a, 08b, 08c 전부 — 후보 모집단이 바뀌었으므로.
   기존 candidates_202606이 있다면 DROP TABLE 후 재생성할 것.

   2026-08-03 수정(region=KR/OS=Android 필터 추가): media/02_pool_media.sql 주석 참고 —
   pool/candidate의 해외·iOS 트래픽이 media 신호를 희석시킨다는 가설을 검증하기 위해
   후보 모집단 자체를 region=KR AND OS=Android로 제한한다(참고: 이 필터는 seed/pool
   segment 쿼리에는 적용돼 있지 않다 — 01_pool_segment.sql 주석 참고).

   2026-08-19 수정(기간 확장 06월→06~08월18일, 테이블명 candidates_202606→
   candidates_202606_0818, seed_je 제외 추가): je 스코어링 결과 상위20%가 30만 명이
   되도록 후보 규모를 664,684명에서 약 150만 명으로 늘리기 위함. skp 세그먼트 매칭
   조건(가장 큰 축소 요인)과 region=KR/OS=Android 필터는 후보 품질 유지를 위해 그대로
   두고, 학습 기간(pool/seed=2026-04~05)과 겹치지 않는 06~08월 범위로만 기간을 넓혔다
   (08월은 실행 시점 기준 데이터가 있는 18일까지만 — 그 이후는 아직 파티션이 없을 수
   있어 상한을 명시적으로 건다). 같은 김에 seed_je_ad_id도 제외 조건에 추가했다 —
   기존엔 seed_piellaven만 제외해 je seed 본인 1,063명이 후보에 섞여 있었다
   (summary_note/20260819_je_seed_segment_기반_룩어라이크_스코어링_요약.md 0-1절 참고).

   **재실행 필요**: 이 파일, segment/04_candidate_segment.sql 전부 — 후보 모집단이
   바뀌었으므로. 기존 candidates_202606_0818이 있다면 DROP TABLE 후 재생성할 것
   (candidates_202606은 그대로 두고 새 테이블명으로 분리 — 기존 결과와 비교 가능하게).
   2026-08-25 수정(기간 재확장 06~08/18 -> 04/01~08/24, 테이블명 candidates_202606_0818 ->
   candidates_20260401_0824): 후보 규모를 더 늘리기 위해 bid log 조회 기간을 약 4.8개월로
   넓혔다. 유지한 것: skp 세그먼트 매칭 조건, region=KR/OS=Android 필터, seed_piellaven/
   seed_je 제외. 바뀐 것은 기간뿐이다.

   학습 기간과의 겹침에 대해(CLAUDE.md "학습/스코어링 기간 분리" 규칙): 이 확장은
   학습 기간(pool/seed = 2026-04~05)과 겹치지만, segment 트랙에서는 실질적인 leakage가
   아니다 — (1) segment 트랙의 pool(01_pool_segment.sql)은 bid log가 아니라 propfit.skp
   전체에서 device_ifa 해시 5% 표본으로 뽑으므로 애초에 기간 개념이 없다. 후보와 pool의
   겹침은 기간이 아니라 그 5% 해시로만 결정되고, 기간을 넓혀도 겹침 "비율"은 변하지
   않는다. (2) 피처(04_candidate_segment.sql)도 skp의 "가장 최근 레코드" 기준이라 조회
   기간과 무관하다 — 기간을 넓혀도 개별 유저의 피처 벡터는 그대로고 후보 명단만 늘어난다.
   즉 이 규칙이 막으려던 "학습 시점 이후 정보 유입"은 여기선 발생하지 않는다. 단 media
   트랙(media/04_create_candidate_table_media.sql)은 피처 자체가 기간 의존이라 같은 논리가
   적용되지 않는다 — 그쪽을 확장할 땐 다시 판단할 것.

   08/24 상한: 실행 시점(2026-08-25) 기준 전날까지로 잡은 값이다 — 08/24 파티션이 실제로
   적재돼 있는지는 확인하지 못했으니, 결과 건수가 예상보다 적으면 상한을 낮춰볼 것.

   규모 예상: 06~08/18(약 2.5개월)이 약 150만 명이었으므로 04/01~08/24(약 4.8개월)는
   200만 명 이상으로 예상된다(스캔량도 그만큼 늘어난다).

   **재실행 필요**: 이 파일, segment/04_candidate_segment.sql 전부. 기존
   candidates_202606_0818은 비교용으로 그대로 두고 새 테이블명으로 분리한다.

   2026-08-26 수정(seed_shoplinker 제외 추가, pipeline/generate_seed_queries.py 자동 생성): candidate가 신규 seed(shoplinker) 본인을 포함하지 않도록 LEFT JOIN seed_shoplinker_ad_id + AND s_shoplinker.device_ifa IS NULL을 추가했다.
   **재실행 필요**: 이 파일, segment/04_candidate_segment.sql — candidate 모집단이 바뀌므로.

   2026-08-26 수정(테이블명 candidates_20260401_0824 -> candidates_shoplinker_20260601_0824,
   기간 04/01~08/24 -> 06/01~08/24): shoplinker 전용 후보 테이블로 분리하고, 기간에서
   04~05월(학습 기간과 겹치는 구간)을 제외했다. 기존 candidates_20260401_0824는 그대로
   두고(다른 seed/variant가 참조 중이면 유지), 이 테이블은 shoplinker 스코어링 전용.
   **재실행 필요**: 이 파일, segment/04_candidate_segment.sql.
   ============================================================ */

CREATE TABLE candidates_shoplinker_20260601_0824
WITH (format = 'PARQUET')
AS
SELECT DISTINCT b.device_ifa
FROM "prod-ptbwa-dw"."abi_bid_log_flatten" b
LEFT JOIN seed_piellaven_ad_id sd ON b.device_ifa = sd.device_ifa
LEFT JOIN seed_je_ad_id sj ON b.device_ifa = sj.device_ifa
LEFT JOIN seed_shoplinker_ad_id s_shoplinker ON b.device_ifa = s_shoplinker.device_ifa
JOIN (
    SELECT ad_id AS device_ifa
    FROM (
        SELECT
            ad_id,
            ROW_NUMBER() OVER (
                PARTITION BY ad_id
                ORDER BY year DESC, month DESC, day DESC
            ) AS rn
        FROM "propfit"."skp"
        WHERE NOT (year = '2024' AND month = '12' AND day = '31')
          AND CAST(id_type AS VARCHAR) = '2'
          AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
    ) x
    WHERE rn = 1
) seg ON b.device_ifa = seg.device_ifa
WHERE b.year = '2026'
  AND (b.month IN ('06', '07') OR (b.month = '08' AND CAST(b.day AS INTEGER) <= 24))
  AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
  AND regexp_like(CAST(b.device_ifa AS VARCHAR), '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
  AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
  AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
  AND sd.device_ifa IS NULL
  AND sj.device_ifa IS NULL
  AND s_shoplinker.device_ifa IS NULL
  AND CAST(b.device_geo_region AS VARCHAR) LIKE 'KR%'
  AND regexp_like(CAST(b.device_osv AS VARCHAR), '^[0-9]+$');
