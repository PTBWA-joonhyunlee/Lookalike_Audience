-- ============================================================
-- 00_id_mapping_check.sql (propfit)
-- 목적: 01_user_profile.sql / 03_user_segments.sql이 쓰는 ptbwa_skb 크로스워크 조인 키가
--       맞는지 확인하는 진단 쿼리. 결과 실행 전까지는 절대 확정하지 말 것.
--
-- 문제 상황: "propfit"."ptbwa_skb"는 (uuid, platform_ad_id, ad_id) 세 컬럼을 갖는다.
--   - 사용자가 준 원본 쿼리는 skb.ad_id = abi_bid_log_flatten.device_ifa로 조인했다
--     (즉 skb.ad_id는 device_ifa와 같은 공간이라는 근거).
--   - 그런데 ptbwa_tg의 키 컬럼명은 "uuid", skp의 키 컬럼명은 "ad_id"다 — 컬럼명만 보면
--     ptbwa_tg.uuid ↔ ptbwa_skb.uuid, skp.ad_id ↔ ptbwa_skb.ad_id로 매칭되는 게 자연스럽다.
--   - 이 이름 매칭이 맞다면 skp.ad_id는 이미 device_ifa와 같은 공간(크로스워크 불필요)이고,
--     01_user_profile.sql의 profile 조인은 platform_ad_id가 아니라 uuid를 거쳐야 한다.
--   - 즉 "platform_ad_id"가 실제로 어떤 ID 공간인지 아직 불확실 — 01/03에 이미 넣어둔
--     "skb.ad_id → platform_ad_id → ptbwa_tg.uuid/skp.ad_id" 크로스워크는 검증 전 가정이다.
--
-- 사용법: 아래 4개 카운트를 비교한다. 각 쌍(skp/ptbwa_tg)에서 매칭 건수가 확연히 큰 쪽이
--   실제 조인 키다(0에 가까운 쪽은 틀린 가정). 결과를 알려주면 01/03의 크로스워크를 그에
--   맞게 고친다.
--
-- 파티션 이슈(2026-07-23): skp를 필터 없이 전체 스캔하면 year=2024/month=12/day=31
--   파티션의 깨진 .tmp 파일에서 HIVE_CURSOR_ERROR가 난다(03_user_segments.sql에서 이미
--   겪음). 이 진단은 기간이 아니라 "ID 공간이 겹치는지"만 보는 게 목적이라 특정 기간으로
--   좁히지 않고, 문제의 파티션 하나만 명시적으로 제외했다 — 그래야 실제 매칭 건수를
--   왜곡 없이 볼 수 있다.
-- ============================================================

SELECT
    (SELECT count(*) FROM "propfit"."skp" s
        JOIN "propfit"."ptbwa_skb" k ON CAST(s.ad_id AS VARCHAR) = CAST(k.ad_id AS VARCHAR)
        WHERE NOT (s.year = '2024' AND s.month = '12' AND s.day = '31')
    ) AS skp_matches_via_skb_ad_id,
    (SELECT count(*) FROM "propfit"."skp" s
        JOIN "propfit"."ptbwa_skb" k ON CAST(s.ad_id AS VARCHAR) = CAST(k.platform_ad_id AS VARCHAR)
        WHERE NOT (s.year = '2024' AND s.month = '12' AND s.day = '31')
    ) AS skp_matches_via_skb_platform_ad_id,
    (SELECT count(*) FROM "propfit"."ptbwa_tg" t
        JOIN "propfit"."ptbwa_skb" k ON CAST(t.uuid AS VARCHAR) = CAST(k.uuid AS VARCHAR)
    ) AS ptbwa_tg_matches_via_skb_uuid,
    (SELECT count(*) FROM "propfit"."ptbwa_tg" t
        JOIN "propfit"."ptbwa_skb" k ON CAST(t.uuid AS VARCHAR) = CAST(k.platform_ad_id AS VARCHAR)
    ) AS ptbwa_tg_matches_via_skb_platform_ad_id;
