/* ============================================================
   04a_seed_profile.sql (seed, 구 05a_seed_profile.sql)
   01_user_profile.sql(propfit)과 동일 로직, device_ifa를 seed_piellaven_ad_id(02에서
   만든 크로스워크 결과, 진짜 GAID 공간)로 제한. 전수 추출(샘플링 없음).

   2026-08-03 수정(region=KR/OS=Android 필터 추가): `summary_note/20260803_...`의 profile
   분석 결과, seed는 이미 region KR 98.4%/Android 99.4%로 사실상 단일 성향인 반면
   pool은 region KR 31.6%(JP 49.6%)/Android 74.9%(iOS 25.1%)로 훨씬 이질적이었다 —
   pool/candidate의 해외(주로 일본)·iOS 트래픽이 media 신호를 희석시킨다는 가설(media
   단독 AUC가 낮았던 원인 중 하나로 의심)을 검증하기 위해, 이번 실험부터 seed/pool/
   candidate 전부 **region=KR AND OS=Android로 모집단 자체를 제한**한다. OS 판별은
   `device_osv` 값 포맷 차이를 이용한다 — Android는 정수형 문자열(예: "16"), iOS는
   점 표기 버전(예: "26.3.1")이라 `regexp_like(..., '^[0-9]+$')`로 Android만 남긴다
   (근거: `summary_note/20260803_...` profile 분석에서 실측 확인, 두 OS가 겹치는 값
   포맷이 없음을 확인함).
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
    JOIN seed_piellaven_ad_id sd ON b.device_ifa = sd.device_ifa
    WHERE b.year = '2026' AND b.month IN ('04', '05')
      AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND CAST(b.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(b.device_osv AS VARCHAR), '^[0-9]+$')
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
