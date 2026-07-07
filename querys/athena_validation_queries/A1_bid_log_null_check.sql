-- A1. bid_log_flatten: 핵심 컬럼 결측률
-- 기대값: null_req_id = 0, null_price/cmp_no/ag_no/deal_id 낮은 비율
SELECT
  count(*) AS total_rows,
  count_if(req_id   IS NULL OR trim(CAST(req_id AS VARCHAR)) = '')   AS null_req_id,
  count_if(media_id IS NULL OR trim(CAST(media_id AS VARCHAR)) = '') AS null_media_id,
  count_if(price    IS NULL OR trim(CAST(price AS VARCHAR)) = '')    AS null_price,
  count_if(cmp_no   IS NULL OR trim(CAST(cmp_no AS VARCHAR)) = '')   AS null_cmp_no,
  count_if(ag_no    IS NULL OR trim(CAST(ag_no AS VARCHAR)) = '')    AS null_ag_no,
  count_if(deal_id  IS NULL OR trim(CAST(deal_id AS VARCHAR)) = '')  AS null_deal_id,
  count_if(device_ifa IS NULL OR trim(CAST(device_ifa AS VARCHAR)) = '') AS null_device_ifa
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07';
