/* ============================================================
   id_space_check/05_seed_skb_crosswalk_check.sql (eda, 구 eda/queries/12_seed_skb_crosswalk_check.sql —
   2026-08-26 id_space_check/ 폴더 이동 + 번호 재부여, 그 이전엔 02c_seed_skb_crosswalk_check.sql) — 최우선 확인
   배경: 01/02a/02b 결과 종합 — seed∩bidlog=135,165명(실제 GAID, 우연 아님) vs
   seed∩skp=1명. skp가 진짜 raw GAID ~5,330만 건을 갖고 있다면 150만 개 진짜 GAID
   리스트와 겹침이 1건일 수는 없다 — 즉 "skp.ad_id가 device_ifa와 곧바로 같은 공간"
   이라는 01_id_mapping_check.sql(2026-07-24)의 결론이 이 seed에는 안 맞을 가능성이 있다.
   그 결론은 skp.ad_id ↔ skb.ad_id 매칭 건수(수십억, fan-out 포함)로 추론한 것이지 값
   포맷을 직접 본 게 아니었다.

   이 쿼리는 seed를 "propfit"."ptbwa_skb"의 세 컬럼(ad_id/platform_ad_id/uuid) 각각과
   직접 대조한다 — 셋 중 하나라도 크게 매칭되면 seed → skb → skp 크로스워크 경로가
   있다는 뜻이고, 그러면 세그먼트 피처를 이 경로로 살릴 수 있다(수정 방법이 있는 경우).
   ============================================================ */

WITH seed AS (
    SELECT DISTINCT device_ifa
    FROM seed_piellaven
    WHERE device_ifa IS NOT NULL
      AND regexp_like(device_ifa, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
)
SELECT
    (SELECT count(*) FROM seed) AS seed_total,
    (SELECT count(*) FROM seed sd
        JOIN (SELECT DISTINCT CAST(ad_id AS VARCHAR) AS v FROM "propfit"."ptbwa_skb" WHERE ad_id IS NOT NULL) k
        ON sd.device_ifa = k.v) AS seed_matches_skb_ad_id,
    (SELECT count(*) FROM seed sd
        JOIN (SELECT DISTINCT CAST(platform_ad_id AS VARCHAR) AS v FROM "propfit"."ptbwa_skb" WHERE platform_ad_id IS NOT NULL) k
        ON sd.device_ifa = k.v) AS seed_matches_skb_platform_ad_id,
    (SELECT count(*) FROM seed sd
        JOIN (SELECT DISTINCT CAST(uuid AS VARCHAR) AS v FROM "propfit"."ptbwa_skb" WHERE uuid IS NOT NULL) k
        ON sd.device_ifa = k.v) AS seed_matches_skb_uuid;
