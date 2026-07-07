-- G7. 캠페인(cmp_no/ag_no)별 노출/참여 사용자 볼륨
-- 어떤 캠페인이 "관심 사용자 리스트"를 만들 만큼 충분한 모수를 가졌는지 확인하는 용도입니다.

WITH exposed AS (
  SELECT cmp_no, ag_no, count(DISTINCT device_ifa) AS exposed_device_cnt
  FROM "prod-ptbwa-dw".addi_bid_log_flatten
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
    AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
    AND cmp_no IS NOT NULL AND trim(CAST(cmp_no AS VARCHAR)) <> ''
  GROUP BY cmp_no, ag_no
),
tiered AS (
  SELECT
    cmp_no, ag_no, ifa,
    max(
      CASE log_type
        WHEN 'i'          THEN 1
        WHEN 'v_start'     THEN 2
        WHEN 'v_firstQ'    THEN 3
        WHEN 'v_mid'       THEN 4
        WHEN 'v_thirdQ'    THEN 5
        WHEN 'v_complete'  THEN 6
        ELSE 0
      END
    ) AS max_tier
  FROM "prod-ptbwa-dw".addi_postback_log
  WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
    AND ifa IS NOT NULL AND trim(CAST(ifa AS VARCHAR)) <> ''
    AND cmp_no IS NOT NULL AND trim(CAST(cmp_no AS VARCHAR)) <> ''
  GROUP BY cmp_no, ag_no, ifa
),
engaged AS (
  SELECT
    cmp_no, ag_no,
    count(DISTINCT ifa) AS any_engagement_device_cnt,
    count(DISTINCT CASE WHEN max_tier >= 4 THEN ifa END) AS reached_mid_device_cnt,
    count(DISTINCT CASE WHEN max_tier >= 6 THEN ifa END) AS completed_device_cnt
  FROM tiered
  GROUP BY cmp_no, ag_no
)
SELECT
  coalesce(e.cmp_no, g.cmp_no) AS cmp_no,
  coalesce(e.ag_no, g.ag_no)   AS ag_no,
  e.exposed_device_cnt,
  g.any_engagement_device_cnt,
  g.reached_mid_device_cnt,
  g.completed_device_cnt
FROM exposed e
FULL OUTER JOIN engaged g ON e.cmp_no = g.cmp_no AND e.ag_no = g.ag_no
ORDER BY e.exposed_device_cnt DESC NULLS LAST;
