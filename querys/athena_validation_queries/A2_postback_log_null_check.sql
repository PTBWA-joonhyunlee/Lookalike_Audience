-- A2. postback_log: 핵심 컬럼 결측률
SELECT
  count(*) AS total_rows,
  count_if(req_id   IS NULL OR trim(CAST(req_id AS VARCHAR)) = '')   AS null_req_id,
  count_if(log_type IS NULL OR trim(CAST(log_type AS VARCHAR)) = '') AS null_log_type,
  count_if(cmp_no   IS NULL OR trim(CAST(cmp_no AS VARCHAR)) = '')   AS null_cmp_no,
  count_if(ag_no    IS NULL OR trim(CAST(ag_no AS VARCHAR)) = '')    AS null_ag_no,
  count_if(price    IS NULL OR trim(CAST(price AS VARCHAR)) = '')    AS null_price,
  count_if(ifa      IS NULL OR trim(CAST(ifa AS VARCHAR)) = '')      AS null_ifa
FROM "prod-ptbwa-dw".addi_postback_log
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07';
