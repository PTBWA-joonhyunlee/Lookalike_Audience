-- G5. 이용자 동의/광고추적제한(옵트아웃) 관련 컬럼이 실제로 채워지는지 확인
-- device_lmt = 1 이면 "Limit Ad Tracking"(추적 제한) 요청 디바이스 -> 리스트 추출 시 제외 대상
-- req_ext_allow_user_data_collection = 이용자 데이터 활용 동의 여부로 추정
SELECT
  count(*) AS total_rows,
  count_if(device_lmt IS NOT NULL) AS non_null_device_lmt,
  count(DISTINCT device_lmt) AS distinct_device_lmt_values,
  count_if(CAST(device_lmt AS VARCHAR) = '1') AS lmt_opted_out_cnt,
  count_if(req_ext_allow_user_data_collection IS NOT NULL) AS non_null_allow_user_data_collection,
  count(DISTINCT req_ext_allow_user_data_collection) AS distinct_allow_user_data_collection_values
FROM "prod-ptbwa-dw".addi_bid_log_flatten
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07';
