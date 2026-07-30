/* ============================================================
   15_bidlog_device_ifa_format_census.sql (eda, 구 02f_bidlog_device_ifa_format_census.sql)
   배경: data/sample/prod-ptbwa-dw.abi_bid_log_flatten.csv 샘플에서 device_ifa 값이
   "AD8Fdm6grhzH7y5nBbI_dmm..." 같은 70자대 문자열로 보인 행이 있었다(UUID 형식 아님) —
   즉 abi_bid_log_flatten.device_ifa 자체가 raw GAID/IDFA와 다른 형식의 ID가 섞인
   컬럼일 수 있다(교환/익스체인지에 따라 암호화된 ID가 내려오는 경우 흔함).

   이 쿼리는 학습/스코어링 기간(2026-04~05, 컴플라이언스 필터 적용) 모집단에서 실제
   UUID 포맷 device_ifa가 몇 명이나 되는지 잰다 — 신규 후보 pool 설계 시 참고용
   (지금 당장 blocking은 아님 — 02g/02h의 크로스워크 결과가 더 우선).

   2026-07-29 재작성: 최초 버전이 COUNT(DISTINCT ...) 두 번을 71M+ 행 전체에 걸어서
   타임아웃났다 — count(DISTINCT)는 정확 집계라 비용이 크므로, 근사 집계인
   approx_distinct()(HyperLogLog 기반, 오차 ~2.3%)로 바꿔 비용을 줄였다. 정확한 숫자가
   필요해지면(이 근사치로 결론이 애매할 때만) exact count로 다시 시도할 것.
   ============================================================ */

SELECT
    length(CAST(device_ifa AS VARCHAR)) AS device_ifa_len,
    approx_distinct(device_ifa) AS approx_distinct_devices,
    approx_distinct(
        CASE WHEN regexp_like(CAST(device_ifa AS VARCHAR), '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
             THEN device_ifa END
    ) AS approx_uuid_format_devices
FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
WHERE year = '2026' AND month IN ('04', '05')
  AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
  AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
  AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;
