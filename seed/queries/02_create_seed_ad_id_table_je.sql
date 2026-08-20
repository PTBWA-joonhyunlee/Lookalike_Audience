/* ============================================================
   02_create_seed_ad_id_table_je.sql (seed, je 신규 seed — 02_create_seed_ad_id_table.sql
   [피엘라벤]과 달리 크로스워크 불필요)
   배경: 28_seed_je_id_space_check.sql 결과(2026-08-19) — seed_je(1,922명, UUID 형식)가
   bidlog와 91.5%(1,759명), propfit.skp.ad_id와 60.2%(1,157명) 직접 매칭됐다. 반면
   ptbwa_skb.platform_ad_id 매칭은 0명, ad_id 매칭도 6.8%(130명)뿐 — 피엘라벤 seed(원래
   platform_ad_id 공간, skb 크로스워크 후에야 raw GAID 확보)와 정반대로, 이 seed는 값
   자체가 이미 raw GAID(device_ifa) 공간에 있다. 따라서 skb 크로스워크 단계 없이 정규식
   필터 + DISTINCT만으로 충분하다.

   이후 모든 seed 피처 추출(profile/media/segment)과 "신규 후보(pool − seed)" 판정은
   이 쿼리로 만든 seed_je_ad_id 테이블을 device_ifa 키로 그대로 조인해서 쓴다 —
   seed_piellaven_ad_id와 동일한 역할, 크로스워크 브랜드별로 이름만 분리.
   ============================================================ */

CREATE TABLE seed_je_ad_id
WITH (format = 'PARQUET')
AS
SELECT DISTINCT device_ifa
FROM seed_je
WHERE device_ifa IS NOT NULL
  AND regexp_like(device_ifa, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$');
