/* ============================================================
   05a_pool_profile.sql (seed, 구 06a_pool_profile.sql)
   01_user_profile.sql(propfit)과 동일 로직 + (a) seed_piellaven_ad_id 제외
   (b) 학습용 5% 표본(device_ifa 해시 기준 — 06b/06c와 반드시 같은 키를 써야 같은
   표본 코호트가 세 피처에 걸쳐 일치한다: mod(...,1000) < 50 = 5%). 기간은 seed와
   동일한 2026-04~05(pool/seed가 같은 기간이어야 분류기 학습이 성립).

   2026-07-30 표본 비율 조정: 최초 0.5%(mod(...,1000)<5)로 06a가 350,000행 나왔는데,
   seed(양성, 05a 전수 1,197,069행) 대비 pool(음성)이 더 적어(약 1:0.29) 지도학습에
   불리한 비율이라 사용자 요청으로 5%로 올렸다 — 예상 약 350만 행.

   2026-07-30 수정(1차, 틀림): 0.5% 표본으로 05b_pool_media.sql이 4억 행 나온 걸 보고
   "device_ifa에 요청마다 새로 생기는 암호화 문자열이 섞여 있다"고 의심해 UUID 형식
   필터를 추가했었다 — 그 필터는 유지하되(seed는 skb.ad_id 크로스워크를 거쳐 이미
   UUID 공간이므로, pool도 같은 ID 공간으로 맞추는 게 맞다), 4억 행의 진짜 원인은
   아니었다(UUID 필터로는 전체의 3.7%만 제거됨 — 유령 토큰 가설 기각).

   2026-07-30 수정(2차, 진짜 원인): 06a가 0.5% 표본인데 3,500만 행이 나왔다(전체
   72,254,582명의 약 48.4%) — Trino의 mod()는 피연산자 부호를 따라가는데
   xxhash64/from_big_endian_64는 부호 있는 값을 반환해서, mod(hash,1000)<5가
   "0~4"뿐 아니라 음수 전부(-999~-1)까지 통과시켜 사실상 ~50.25%를 표본으로 뽑고
   있었다(72,254,582 × 0.5025 ≈ 36.3M, 실제 3,500만과 근접). 11_user_embedding_features.sql
   의 원래 1% 필터는 `= 0`(부호 무관하게 안전)였고, addi 쪽 `01_pool_profile_apr_may.sql`은
   crc32(부호 없는 해시)를 썼던 것 — 이번에 `xxhash64` + `< N` 조합을 처음 써서 이
   문제가 드러났다. crc32 기반으로 교체했다.
   ============================================================ */

WITH bidlog_latest AS (
    SELECT
        b.device_ifa,
        b.req_user_id,
        b.device_osv AS device_os_version,
        b.device_geo_region AS region,
        b.app_bundle,
        b.device_carrier AS carrier,
        ROW_NUMBER() OVER (
            PARTITION BY b.device_ifa
            ORDER BY b.created_at DESC
        ) AS rn
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" b
    LEFT JOIN seed_piellaven_ad_id sd ON b.device_ifa = sd.device_ifa
    WHERE b.year = '2026' AND b.month IN ('04', '05')
      AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
      AND regexp_like(CAST(b.device_ifa AS VARCHAR), '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND sd.device_ifa IS NULL   -- seed 제외(양성/음성 라벨 오염 방지)
      AND mod(crc32(to_utf8(CAST(b.device_ifa AS VARCHAR))), 1000) < 50   -- 5% 표본(부호 없는 해시)
)
SELECT
    req_user_id,
    device_ifa,
    device_os_version,
    region,
    app_bundle,
    carrier,
    current_date AS update_dt
FROM bidlog_latest
WHERE rn = 1;
