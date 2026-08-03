/* ============================================================
   05b_pool_media.sql (seed, 구 06b_pool_media.sql)
   02_user_media.sql(propfit)과 동일 로직 + (a) seed_piellaven_ad_id 제외
   (b) 06a와 동일한 5% 표본 키(device_ifa 해시, mod 1000 기준) (c) propfit_media_top500 vocab 참조
   (자체 top500 재계산 안 함, 04 헤더 참고). 표본 비율 0.5%→5% 조정 사유는
   05a_pool_profile.sql 주석 참고(양성/음성 비율 개선).

   원본 02_user_media.sql은 device_ifa를 필터하지 않는다(req_user_id 기준) — 여기서는
   표본 추출/seed 제외에 device_ifa가 반드시 있어야 하므로 device_ifa NOT NULL 조건을
   추가했다(원본과의 의도적 차이).

   2026-07-30 수정: 0.5% 표본으로 4억 행이 나온 진짜 원인은 mod()의 부호 버그였다
   (05a_pool_profile.sql 주석 참고 — xxhash64가 부호 있는 값을 반환해 mod(...,1000)<5가
   사실상 ~50.25%를 통과시켰다, 400M행/3600만 디바이스 ≈ 11 이벤트/디바이스로 밀도
   자체는 정상이었음). crc32(부호 없는 해시)로 교체했다. device_ifa UUID 형식 필터는
   유지 — seed가 skb.ad_id 크로스워크를 거쳐 이미 UUID 공간이므로 ID 공간을 맞추기
   위함(전체의 3.7%만 제거되는 수준이라 이번 행 폭증의 원인은 아니었음).

   2026-08-03 수정(region=KR/OS=Android 필터 추가): 04a_seed_profile.sql 헤더 참고 —
   pool/candidate의 해외·iOS 트래픽이 media 신호를 희석시킨다는 가설을 검증하기 위해
   모집단 자체를 region=KR AND OS=Android로 제한한다.
   ============================================================ */

WITH raw_visit AS (
    SELECT
        v.req_id,
        v.req_user_id,
        v.device_ifa,
        COALESCE(
            NULLIF(CAST(v.app_bundle AS VARCHAR), ''),
            NULLIF(CAST(v.site_page AS VARCHAR), '')
        ) AS media,
        CASE
            WHEN NULLIF(CAST(v.app_bundle AS VARCHAR), '') IS NOT NULL THEN 'app'
            WHEN NULLIF(CAST(v.site_page AS VARCHAR), '') IS NOT NULL THEN 'site'
            ELSE NULL
        END AS inventory_type,
        NULLIF(CAST(v.imp_ad_type AS VARCHAR), '') AS ad_type,
        NULLIF(CAST(v.device_connectiontype AS VARCHAR), '') AS connection_type,
        CAST(from_iso8601_timestamp(CAST(v.created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts,
        v.year
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" v
    LEFT JOIN seed_piellaven_ad_id sd ON v.device_ifa = sd.device_ifa
    WHERE v.year = '2026' AND v.month IN ('04', '05')
      AND v.req_user_id IS NOT NULL AND trim(CAST(v.req_user_id AS VARCHAR)) <> ''
      AND v.device_ifa IS NOT NULL AND trim(CAST(v.device_ifa AS VARCHAR)) <> ''
      AND regexp_like(CAST(v.device_ifa AS VARCHAR), '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
      AND CAST(v.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (v.device_lmt IS NULL OR CAST(v.device_lmt AS VARCHAR) <> '1')
      AND sd.device_ifa IS NULL
      AND CAST(v.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(v.device_osv AS VARCHAR), '^[0-9]+$')
      AND mod(crc32(to_utf8(CAST(v.device_ifa AS VARCHAR))), 1000) < 50
),
top500 AS (
    SELECT
        v.req_id, v.req_user_id, v.device_ifa, v.media,
        v.inventory_type, v.ad_type, v.connection_type, v.ts, v.year
    FROM raw_visit v
    JOIN propfit_media_top500 r ON v.media = r.media
),
flagged AS (
    SELECT
        t.*,
        LAG(media) OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_media,
        LAG(ts)    OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_ts
    FROM top500 t
)
SELECT
    req_id, req_user_id, device_ifa, media, inventory_type, ad_type, connection_type, ts, year
FROM flagged
WHERE prev_media IS NULL
   OR prev_media <> media
   OR date_diff('second', prev_ts, ts) >= 1800
;
