-- J1. 대상 캠페인(cmp_no)의 전체 노출자 + 관심도 티어 분포 (검증/리뷰용)
-- 아래 10115 를 원하는 cmp_no로 교체하세요. (예: cmp_no IN (10115, 10119))

WITH bid_exposure AS (
  SELECT
    b.device_ifa,
    arbitrary(b.req_user_id) AS req_user_id,
    min(b.created_at) AS first_exposed_at,
    max(b.created_at) AS last_exposed_at,
    count(*) AS impression_cnt
  FROM "prod-ptbwa-dw".addi_bid_log_flatten b
  WHERE b.year = '2026' AND b.month = '06' AND b.day BETWEEN '01' AND '07'
    AND CAST(b.cmp_no AS VARCHAR) IN ('10115')  -- << 여기 교체
    AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
    AND regexp_like(CAST(b.device_ifa AS VARCHAR), '^[0-9a-fA-F-]{36}$')
    AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
    AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
  GROUP BY b.device_ifa
),
engagement AS (
  SELECT
    p.ifa AS device_ifa,
    max(
      CASE p.log_type
        WHEN 'i'         THEN 1
        WHEN 'v_start'    THEN 2
        WHEN 'v_firstQ'   THEN 3
        WHEN 'v_mid'      THEN 4
        WHEN 'v_thirdQ'   THEN 5
        WHEN 'v_complete' THEN 6
        ELSE 0
      END
    ) AS max_tier,
    count(DISTINCT p.log_type) AS engagement_stage_cnt,  -- count(*) 대신 distinct 사용: B2에서 확인된 중복 적재(2026-06-02T23:41:13 등) 영향 제거
    max(p.created_at) AS last_engaged_at
  FROM "prod-ptbwa-dw".addi_postback_log p
  WHERE p.year = '2026' AND p.month = '06' AND p.day BETWEEN '01' AND '07'
    AND CAST(p.cmp_no AS VARCHAR) IN ('10115')  -- << 여기도 동일하게 교체
    AND p.ifa IS NOT NULL AND trim(CAST(p.ifa AS VARCHAR)) <> ''
  GROUP BY p.ifa
)
SELECT
  e.device_ifa,
  e.req_user_id,
  e.impression_cnt,
  e.first_exposed_at,
  e.last_exposed_at,
  coalesce(g.max_tier, 0) AS max_engagement_tier,
  CASE
    WHEN coalesce(g.max_tier, 0) >= 6 THEN 'T4_고관여(완료)'
    WHEN coalesce(g.max_tier, 0) >= 4 THEN 'T3_중간참여'
    WHEN coalesce(g.max_tier, 0) >= 1 THEN 'T2_참여시작'
    ELSE 'T1_노출만'
  END AS interest_tier,
  g.engagement_stage_cnt,
  g.last_engaged_at
FROM bid_exposure e
LEFT JOIN engagement g ON e.device_ifa = g.device_ifa
ORDER BY max_engagement_tier DESC, e.impression_cnt DESC;
