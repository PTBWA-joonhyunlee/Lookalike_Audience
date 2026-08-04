/* ============================================================
   05a_pool_profile.sql (seed, 구 06a_pool_profile.sql)
   01_user_profile.sql(propfit)과 동일 로직 + (a) seed_piellaven_ad_id 제외
   (b) 학습용 표본(device_ifa 해시 기준, 현재 20%: mod(...,1000) < 200 — 표본 비율
   변경 이력은 아래 날짜별 항목 참고). 기간은 seed와 동일한 2026-04~05(pool/seed가
   같은 기간이어야 분류기 학습이 성립).

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

   2026-08-03 수정(region=KR/OS=Android 필터 추가): 04a_seed_profile.sql 헤더 참고 —
   pool/candidate의 해외·iOS 트래픽이 media 신호를 희석시킨다는 가설을 검증하기 위해
   모집단 자체를 region=KR AND OS=Android로 제한한다.

   2026-08-03 수정(표본 비율 5%→20% 상향): 위 region/OS 필터를 추가하면서 실측한
   결과, 필터 적용 전 05a_pool_profile.csv(351만 704행) 중 region=KR AND OS=Android를
   동시에 만족하는 행은 27.77%(974,810행)뿐이었다(seed는 97.78~99.19%로 거의 전부
   해당하는 것과 대조적 — pool은 애초에 해외 트래픽 비중이 높아서다). 5% 표본을 그대로
   두면 필터 후 pool 규모가 seed(약 118만 7천 명, 04a 실측)보다 작아지거나 비슷해져
   2026-07-30에 5%로 올렸던 이유(seed 대비 pool이 적어 지도학습에 불리)가 재발한다 —
   `mod(...,1000) < 50`(5%)을 `< 200`(20%)으로 올려 필터 후에도 pool이 seed보다
   충분히 크도록(대략 27.77% × 20% ≈ 5.5%, 필터 전 5% 표본 규모와 비슷한 수준으로)
   맞췄다.
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
      AND CAST(b.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(b.device_osv AS VARCHAR), '^[0-9]+$')
      AND mod(crc32(to_utf8(CAST(b.device_ifa AS VARCHAR))), 1000) < 200   -- 20% 표본(부호 없는 해시)
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
