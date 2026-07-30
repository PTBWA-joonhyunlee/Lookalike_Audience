/* ============================================================
   20_candidate_segment_case_check.sql (eda, 구 09b_candidate_segment_case_check.sql)
   배경: 09_case_sensitivity_check.sql과 같은 배경(대소문자 조인 문제 의심) — 이번엔
   08c_candidate_segment.sql이 직접 겪은 경우(candidates_202606 ↔ skp.ad_id)를
   같은 방식으로 대소문자 구분/무시 두 버전으로 재보아 실제 개선 폭을 수치로 잰다.
   candidates_202606은 이미 만들어져 있으므로(07 실행 완료) 그대로 재사용.
   ============================================================ */

WITH segments_latest AS (
    SELECT
        ad_id AS device_ifa,
        ROW_NUMBER() OVER (
            PARTITION BY ad_id
            ORDER BY year DESC, month DESC, day DESC
        ) AS rn
    FROM "propfit"."skp"
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')
      AND CAST(id_type AS VARCHAR) = '2'
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
),
skp_ids AS (
    SELECT device_ifa FROM segments_latest WHERE rn = 1
)
SELECT
    (SELECT count(*) FROM candidates_202606) AS candidates_total,
    (SELECT count(*) FROM candidates_202606 c
        JOIN skp_ids s ON c.device_ifa = s.device_ifa) AS case_sensitive_match,
    (SELECT count(*) FROM candidates_202606 c
        JOIN skp_ids s ON lower(c.device_ifa) = lower(s.device_ifa)) AS case_insensitive_match
;
