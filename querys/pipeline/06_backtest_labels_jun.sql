-- ============================================================
-- 06_backtest_labels_jun.sql
-- 목적: 6월 postback 발생 유저(ifa) 전원에 대해 raw_conv_web(_imp) mall_ip 매칭 여부를 ifa
--       그레인으로 만든다(매칭 안 된 유저도 0으로 포함 — LEFT JOIN). 07/08(스코어링 대상)로
--       뽑은 스코어에 바로 붙여서 evaluation.backtest를 돌릴 수 있다(cumulative_topk_summary로
--       "전체 postback 유저 전환율 vs 상위 10/20/30%...% 전환율" 확인 — README 참고).
-- 매칭 정의: mall_ip=postback.ip, mall_datetime이 postback 이후(음수 시간차 제외). 여러 후보를
--       한번에 뽑아둔다(사전 진단 히스토리는 docs/_archive/202607091533.md 참고):
--         conv_matched_ip_cmp_any_window   : IP+cmp_no 일치, 시간창 제한 없음
--         conv_matched_ip_cmp_7d/_30d      : 위에 시간창 추가
--         conv_matched_ip_any_cmp_any_window: cmp_no 무시, IP만 일치 (기본값 — 표본 확보 우선)
--         conv_matched_order_only          : ev='order'(실제 구매)로 제한 — order 이벤트가
--                                             시스템 전체에 ~60건뿐이라 거의 항상 0(참고용)
-- 컴플라이언스 필터 없음 — 이미 스코어링 대상(07/08) 자체가 동의 유저로 필터링됨.
-- ============================================================

WITH postback_ifa AS (
  SELECT DISTINCT ifa
  FROM "prod-ptbwa-dw".addi_postback_log
  WHERE year = '2026' AND month = '06'
),
postback_ip AS (
  SELECT
    ifa,
    CAST(ip AS VARCHAR) AS ip,
    CAST(cmp_no AS VARCHAR) AS cmp_no,
    min(created_at) AS first_created_at
  FROM "prod-ptbwa-dw".addi_postback_log
  WHERE year = '2026' AND month = '06'
    AND ip IS NOT NULL AND trim(CAST(ip AS VARCHAR)) <> ''
  GROUP BY ifa, CAST(ip AS VARCHAR), CAST(cmp_no AS VARCHAR)
),
conv AS (
  SELECT
    CAST(mall_ip AS VARCHAR) AS mall_ip,
    CAST(cmp_no AS VARCHAR) AS cmp_no,
    ev,
    CAST(regexp_replace(CAST(mall_datetime AS VARCHAR), 'T', ' ') AS TIMESTAMP) AS mall_ts
  FROM "prod_addi_conv".raw_conv_web

  UNION ALL

  SELECT
    CAST(mall_ip AS VARCHAR) AS mall_ip,
    CAST(cmp_no AS VARCHAR) AS cmp_no,
    ev,
    CAST(regexp_replace(CAST(mall_datetime AS VARCHAR), 'T', ' ') AS TIMESTAMP) AS mall_ts
  FROM "prod_addi_conv".raw_conv_web_imp
),
joined AS (
  SELECT
    p.ifa,
    (p.cmp_no = c.cmp_no) AS cmp_no_match,
    c.ev,
    date_diff(
      'hour',
      CAST(regexp_replace(CAST(p.first_created_at AS VARCHAR), 'T', ' ') AS TIMESTAMP),
      c.mall_ts
    ) AS hours_diff
  FROM postback_ip p
  JOIN conv c ON p.ip = c.mall_ip
  WHERE date_diff(
      'hour',
      CAST(regexp_replace(CAST(p.first_created_at AS VARCHAR), 'T', ' ') AS TIMESTAMP),
      c.mall_ts
    ) >= 0
),
matched_agg AS (
  SELECT
    ifa,
    max(CASE WHEN cmp_no_match THEN 1 ELSE 0 END) AS m_ip_cmp_any,
    max(CASE WHEN cmp_no_match AND hours_diff <= 168 THEN 1 ELSE 0 END) AS m_ip_cmp_7d,
    max(CASE WHEN cmp_no_match AND hours_diff <= 720 THEN 1 ELSE 0 END) AS m_ip_cmp_30d,
    max(1) AS m_ip_any_cmp_any,
    max(CASE WHEN cmp_no_match AND ev = 'order' THEN 1 ELSE 0 END) AS m_order_only
  FROM joined
  GROUP BY ifa
)
SELECT
  b.ifa,
  coalesce(m.m_ip_cmp_any, 0) AS conv_matched_ip_cmp_any_window,
  coalesce(m.m_ip_cmp_7d, 0) AS conv_matched_ip_cmp_7d,
  coalesce(m.m_ip_cmp_30d, 0) AS conv_matched_ip_cmp_30d,
  coalesce(m.m_ip_any_cmp_any, 0) AS conv_matched_ip_any_cmp_any_window,
  coalesce(m.m_order_only, 0) AS conv_matched_order_only
FROM postback_ifa b
LEFT JOIN matched_agg m ON b.ifa = m.ifa;
