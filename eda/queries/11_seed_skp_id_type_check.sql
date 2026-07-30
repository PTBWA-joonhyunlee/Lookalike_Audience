/* ============================================================
   11_seed_skp_id_type_check.sql (eda, 구 propfit/seed_lookalike/02b_seed_skp_id_type_check.sql)
   배경: 01_seed_coverage_check.sql 결과 — seed_in_segments=1(0.0%), 비정상적으로 낮음
   (자세한 배경은 02_seed_segment_anomaly_check.sql 참고 — Athena가 한 파일에
   statement 하나만 허용해 (A)/(B)를 파일로 분리했다).

   가설 B: id_type='2' 필터가 이 seed population에는 안 맞는 값이라 다른 id_type으로
   존재할 수 있음. 이 쿼리는 id_type 필터를 없애고 seed가 propfit.skp.ad_id와 어떤
   id_type으로든 매칭되는지, 있다면 어느 id_type인지 확인한다.
   ============================================================ */

WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM seed_piellaven
    WHERE device_ifa IS NOT NULL
      AND regexp_like(device_ifa, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
),
skp_any AS (
    SELECT DISTINCT ad_id AS device_ifa, CAST(id_type AS VARCHAR) AS id_type
    FROM "propfit"."skp"
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
)
SELECT
    k.id_type,
    count(*) AS match_cnt
FROM seed sd
JOIN skp_any k ON sd.device_ifa = k.device_ifa
GROUP BY k.id_type
ORDER BY match_cnt DESC;
