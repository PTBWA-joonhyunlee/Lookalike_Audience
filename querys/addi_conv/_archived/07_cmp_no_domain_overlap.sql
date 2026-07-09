-- ============================================================
-- 07_cmp_no_domain_overlap.sql
-- 목적: raw_conv_web(_imp)의 cmp_no가 addi_postback_log/addi_bid_log_flatten의 cmp_no와
--       실제로 같은 캠페인 ID 체계인지 확인한다(샘플에서 본 10030/10059/10081/10090/10092가
--       addi 캠페인 cmp_no 10000번대와 우연히 겹치는 범위인지, 진짜 동일 캠페인을 가리키는지).
--       겹친다면 이후 매칭 쿼리에서 IP 단독이 아니라 cmp_no+mall_ip로 훨씬 안전하게 매칭할 수 있다.
-- 기간: postback은 2026-04~05(학습 시드 기간), conv_web은 전체(파티션 없이, row 수 적어 무관).
-- ============================================================

WITH postback_cmp AS (
  SELECT DISTINCT CAST(cmp_no AS VARCHAR) AS cmp_no
  FROM "prod-ptbwa-dw".addi_postback_log
  WHERE year = '2026' AND month IN ('04', '05')
),
conv_cmp AS (
  SELECT DISTINCT CAST(cmp_no AS VARCHAR) AS cmp_no FROM "prod_addi_conv".raw_conv_web
  UNION
  SELECT DISTINCT CAST(cmp_no AS VARCHAR) AS cmp_no FROM "prod_addi_conv".raw_conv_web_imp
)
SELECT
  (SELECT count(*) FROM postback_cmp) AS postback_distinct_cmp_no,
  (SELECT count(*) FROM conv_cmp) AS conv_distinct_cmp_no,
  (SELECT count(*) FROM postback_cmp p JOIN conv_cmp c ON p.cmp_no = c.cmp_no) AS overlapping_cmp_no;
