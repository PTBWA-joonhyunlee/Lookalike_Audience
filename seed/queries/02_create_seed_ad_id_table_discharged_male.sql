/* ============================================================
   02_create_seed_ad_id_table_discharged_male.sql (seed, discharged_male 신규 seed — 크로스워크
   불필요, pipeline/generate_seed_queries.py가 id space 판정 결과로 자동 생성)
   판정 근거(eda/queries id_space_check 결과, seed_total=200379):
   direct 매칭률(skp_direct/skb_ad_id 중 최댓값)=100.0% — 임계값
   10% 이상이라 이미 raw GAID(device_ifa) 공간으로 판정, skb 크로스워크
   없이 정규식 필터 + DISTINCT만 쓴다.

   이후 모든 seed 피처 추출(segment)과 "신규 후보(pool - seed)" 판정은 이 쿼리로 만든
   seed_discharged_male_ad_id 테이블을 device_ifa 키로 그대로 조인해서 쓴다.
   ============================================================ */

CREATE TABLE seed_discharged_male_ad_id
WITH (format = 'PARQUET')
AS
SELECT DISTINCT device_ifa
FROM seed_discharged_male
WHERE device_ifa IS NOT NULL
  AND regexp_like(device_ifa, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$');
