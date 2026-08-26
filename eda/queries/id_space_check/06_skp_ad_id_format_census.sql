/* ============================================================
   id_space_check/06_skp_ad_id_format_census.sql (eda, 구 eda/queries/13_skp_ad_id_format_census.sql —
   2026-08-26 id_space_check/ 폴더 이동 + 번호 재부여, 그 이전엔 02d_skp_ad_id_format_census.sql)
   배경: seed∩skp 매칭이 통계적으로 불가능할 만큼 낮아(02c 주석 참고), skp.ad_id가
   raw GAID(UUID 8-4-4-4-12) 공간이 맞는지부터 직접 확인한다. 길이별 분포를 보고,
   길이가 36이라도 실제로 UUID 정규식과 일치하는지(대소문자/구분자 차이 배제)까지
   같이 센다.
   ============================================================ */

SELECT
    length(CAST(ad_id AS VARCHAR)) AS ad_id_len,
    count(DISTINCT ad_id) AS distinct_devices,
    count(DISTINCT ad_id) FILTER (
        WHERE regexp_like(CAST(ad_id AS VARCHAR), '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
    ) AS uuid_format_devices
FROM "propfit"."skp"
WHERE NOT (year = '2024' AND month = '12' AND day = '31')
  AND CAST(id_type AS VARCHAR) = '2'
  AND ad_id IS NOT NULL
GROUP BY 1
ORDER BY 2 DESC
LIMIT 20;
