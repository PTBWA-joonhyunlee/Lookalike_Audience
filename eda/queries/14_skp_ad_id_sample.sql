/* ============================================================
   14_skp_ad_id_sample.sql (eda, 구 02e_skp_ad_id_sample.sql)
   배경: 02d의 길이 분포만으로는 실제 값 모양을 알 수 없다 — 눈으로 직접 확인하기 위해
   skp.ad_id 원본 값 몇 개를 그대로 뽑는다(02c/02d와 같이 보고 판단할 것).
   ============================================================ */

SELECT DISTINCT ad_id
FROM "propfit"."skp"
WHERE NOT (year = '2024' AND month = '12' AND day = '31')
  AND CAST(id_type AS VARCHAR) = '2'
  AND ad_id IS NOT NULL
LIMIT 20;
