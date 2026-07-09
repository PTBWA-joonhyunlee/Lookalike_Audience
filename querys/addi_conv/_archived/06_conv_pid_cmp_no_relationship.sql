-- ============================================================
-- 06_conv_pid_cmp_no_relationship.sql
-- 목적: pid가 유저(방문자) 식별자인지, 캠페인당 고정된 픽셀/게시물 토큰인지 확인한다.
--       샘플(02/03)에서는 cmp_no=10030이면 항상 pid='T4X9L2H7Q8M3RZK'로 고정되어 보였다
--       (동일 cmp_no, 서로 다른 mall_ip/시각인데 pid만 반복) — 즉 pid는 유저 단위가 아니라
--       cmp_no당 1개(또는 소수)로 보인다. distinct_pid_cnt가 cmp_no당 1에 가까우면 확정.
-- ============================================================

SELECT
  table_name,
  cmp_no,
  count(DISTINCT pid) AS distinct_pid_cnt,
  count(*) AS rows,
  count(DISTINCT mall_ip) AS distinct_mall_ip
FROM (
  SELECT 'raw_conv_web' AS table_name, cmp_no, pid, mall_ip FROM "prod_addi_conv".raw_conv_web
  UNION ALL
  SELECT 'raw_conv_web_imp' AS table_name, cmp_no, pid, mall_ip FROM "prod_addi_conv".raw_conv_web_imp
)
GROUP BY table_name, cmp_no
ORDER BY table_name, cmp_no;
