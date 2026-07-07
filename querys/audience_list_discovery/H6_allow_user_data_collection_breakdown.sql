-- H6. req_ext_allow_user_data_collection 실제 값 분포
-- G5에서 96% 채워져 있고 distinct 값 2개로 확인됨 - 어떤 값이 "동의"를 의미하는지 확인
SELECT
  req_ext_allow_user_data_collection,
  count(*) AS cnt
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
GROUP BY req_ext_allow_user_data_collection
ORDER BY cnt DESC;
