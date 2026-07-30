/* ============================================================
   02_create_seed_ad_id_table.sql (seed, 구 03_create_seed_ad_id_table.sql)
   배경: 02c~02i로 확인됨 — seed(피엘라벤_seed.csv)의 device_ifa는 raw GAID가 아니라
   ptbwa_skb.platform_ad_id 공간에 있다. 이 공간을 skb.ad_id(raw GAID)로 크로스워크하면
   seed 유저의 50.9%가 bidlog에, 61.0%가 segment에 매칭된다(직접 조인 시 8.9%/0.0%였던
   것과 대비) — 이 크로스워크가 이번 트랙의 핵심 전제다.

   이후 모든 seed 피처 추출(profile/media/segment)과 "신규 후보(pool − seed)" 판정은
   이 쿼리로 만든 seed_piellaven_ad_id 테이블(진짜 GAID 공간)을 device_ifa 키로 그대로
   조인해서 쓴다 — 매번 seed_piellaven → ptbwa_skb 크로스워크를 반복하지 않기 위함.

   규모 주의: 크로스워크가 1:N이라(하나의 platform_ad_id가 여러 ad_id로 매핑) 이 테이블의
   행 수(distinct ad_id, 02g 기준 2,519,634)가 원본 seed_total(1,518,101)보다 크다 —
   같은 유저의 서로 다른 시점 GAID(리셋 이력 등)가 여러 개 남아있는 것으로 추정, 실제
   중복 유저 수는 아니다(이 프로젝트의 다른 모든 피처가 device_ifa/ad_id 그레인이므로
   이대로 두는 게 일관적).
   ============================================================ */

CREATE TABLE seed_piellaven_ad_id
WITH (format = 'PARQUET')
AS
WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM seed_piellaven
    WHERE device_ifa IS NOT NULL
      AND regexp_like(device_ifa, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
),
skb AS (
    SELECT DISTINCT
        CAST(platform_ad_id AS VARCHAR) AS platform_ad_id,
        CAST(ad_id AS VARCHAR) AS ad_id
    FROM "propfit"."ptbwa_skb"
    WHERE platform_ad_id IS NOT NULL AND ad_id IS NOT NULL
)
SELECT DISTINCT k.ad_id AS device_ifa
FROM seed sd
JOIN skb k ON sd.device_ifa = k.platform_ad_id;
