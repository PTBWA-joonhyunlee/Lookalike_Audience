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
   ============================================================ */

CREATE TABLE candidates_202606
WITH (format = 'PARQUET')
AS
SELECT DISTINCT b.device_ifa
FROM "prod-ptbwa-dw"."abi_bid_log_flatten" b
LEFT JOIN seed_piellaven_ad_id sd ON b.device_ifa = sd.device_ifa
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
WHERE b.year = '2026' AND b.month = '06'
  AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
  AND regexp_like(CAST(b.device_ifa AS VARCHAR), '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
  AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
  AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
  AND sd.device_ifa IS NULL
  AND CAST(b.device_geo_region AS VARCHAR) LIKE 'KR%'
  AND regexp_like(CAST(b.device_osv AS VARCHAR), '^[0-9]+$');
