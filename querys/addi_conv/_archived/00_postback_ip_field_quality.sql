-- ============================================================
-- 00_postback_ip_field_quality.sql
-- 목적: addi_postback_log의 ip/request_ip 필드 품질 사전 점검 — 전환(postback) 유저를
--       prod_addi_conv.raw_conv_web(_imp)의 mall_ip와 IP로 매칭하기 전에, 이 매칭이 얼마나
--       신뢰할 수 있는지 가늠한다.
-- 확인 항목: 결측률, IPv4 형식 여부, ip vs request_ip 일치율, IP 하나에 몰리는 distinct ifa 수
--       (공유 IP/NAT로 인한 오매칭 위험 — 값이 크면 시간창/추가 조건 없이는 순수 IP 매칭이
--       위험하다는 신호).
-- 기간: 2026-04~05 (학습 시드 기간과 동일, 03_seed_interested_users_apr_may.sql 참고).
-- 컴플라이언스 필터는 적용하지 않음(postback_log 자체는 bid_exposure 단계에서 이미 필터링된
--       유저의 이벤트만 남는 게 아니라 전체이므로, 03/06과 동일하게 여기서는 필터링 안 함).
-- ============================================================

WITH base AS (
  SELECT
    ifa,
    CAST(ip AS VARCHAR) AS ip,
    CAST(request_ip AS VARCHAR) AS request_ip
  FROM "prod-ptbwa-dw".addi_postback_log
  WHERE year = '2026' AND month IN ('04', '05')
),
metrics AS (
  SELECT
    count(*) AS total_rows,
    count_if(ip IS NULL OR trim(ip) = '') AS null_ip,
    count_if(request_ip IS NULL OR trim(request_ip) = '') AS null_request_ip,
    count_if(
      ip IS NOT NULL AND trim(ip) <> ''
      AND NOT regexp_like(ip, '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
    ) AS ip_non_ipv4_format,
    count(DISTINCT ip) AS distinct_ip,
    count_if(ip IS NOT NULL AND request_ip IS NOT NULL AND ip = request_ip) AS ip_eq_request_ip
  FROM base
),
ip_fanout AS (
  SELECT ip, count(DISTINCT ifa) AS distinct_ifa_cnt
  FROM base
  WHERE ip IS NOT NULL AND trim(ip) <> ''
  GROUP BY ip
),
fanout_agg AS (
  SELECT
    count(*) AS distinct_ip_with_ifa,
    avg(distinct_ifa_cnt) AS avg_ifa_per_ip,
    approx_percentile(distinct_ifa_cnt, 0.5) AS median_ifa_per_ip,
    approx_percentile(distinct_ifa_cnt, 0.99) AS p99_ifa_per_ip,
    max(distinct_ifa_cnt) AS max_ifa_per_ip
  FROM ip_fanout
)
SELECT *
FROM metrics
CROSS JOIN fanout_agg;
