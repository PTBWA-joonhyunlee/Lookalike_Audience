-- ============================================================
-- 05_conv_ev_cate_distribution.sql
-- 목적: ev(이벤트 타입)/cate 값 분포 확인 — 02/03 샘플에서는 ev='page_view'만 보였는데,
--       이게 유일한 값이면 "전환"이 아니라 "몰 페이지 방문"에 가깝다는 뜻이라 사용자에게
--       확인이 필요하다. cate('Addi'/'ODM' 등)가 무엇을 구분하는지도 같이 본다.
-- ============================================================

SELECT 'raw_conv_web' AS table_name, ev, cate, count(*) AS n
FROM "prod_addi_conv".raw_conv_web
GROUP BY ev, cate

UNION ALL

SELECT 'raw_conv_web_imp' AS table_name, ev, cate, count(*) AS n
FROM "prod_addi_conv".raw_conv_web_imp
GROUP BY ev, cate

ORDER BY table_name, n DESC;
