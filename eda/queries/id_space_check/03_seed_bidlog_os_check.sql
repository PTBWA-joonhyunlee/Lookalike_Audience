/* ============================================================
   id_space_check/03_seed_bidlog_os_check.sql (eda, 구 eda/queries/10_seed_bidlog_os_check.sql —
   2026-08-26 id_space_check/ 폴더 이동 + 번호 재부여, 그 이전엔 propfit/seed_lookalike/02a_seed_bidlog_os_check.sql)
   배경: 01_seed_coverage_check.sql 결과 — seed_in_bidlog=135,165(8.9%),
   seed_in_segments=1(0.0%). bidlog는 그럭저럭 매칭되는데 segments(propfit.skp)는
   거의 0에 가까워 이상하다(자세한 배경은 02_seed_segment_anomaly_check.sql 참고 —
   Athena가 한 파일에 statement 하나만 허용해 (A)/(B)를 파일로 분리했다).

   가설 A: seed가 iOS 편중 — 한국 DMP(skp) 세그먼트 태깅은 보통 Android GAID 위주라
   iOS IDFA 커버리지가 극히 낮다. bidlog는 iOS도 노출/기록되지만 skp DMP가 iOS를
   거의 못 보는 것이라면 이 격차가 설명된다. 이 쿼리는 seed ∩ bidlog(135,165명)의
   device_os 분포를 본다 — iOS 비중이 압도적으로 높으면(예: 90%+) 이 가설 지지.
   ============================================================ */

WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM seed_piellaven
    WHERE device_ifa IS NOT NULL
      AND regexp_like(device_ifa, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
),
bidlog AS (
    SELECT DISTINCT device_ifa, device_os
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
)
SELECT
    b.device_os,
    count(*) AS device_cnt,
    round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
FROM seed sd
JOIN bidlog b ON sd.device_ifa = b.device_ifa
GROUP BY b.device_os
ORDER BY device_cnt DESC;
