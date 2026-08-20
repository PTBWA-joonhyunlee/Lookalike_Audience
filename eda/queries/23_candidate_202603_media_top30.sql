/* ============================================================
   23_candidate_202603_media_top30.sql (eda, 2026-08-04)
   목적: 5-1 이슈("com.skb.adui`/`com.dcinside.app.android` 반복방문자로 candidate가
   쏠린 게 6월 데이터 자체의 문제인지, 매달 반복되는 구조적 편향인지 확인)를 가볍게
   검증하기 위해, media/04_create_candidate_table_media.sql과 완전히 동일한 population
   정의(seed 제외+region=KR+OS=Android+top500 미디어 30분dedup 5회 이상)를 2026-03에
   적용하고 top30 media 방문자 비율만 집계한다 — 이벤트 그레인 CSV를 뽑지 않고 Athena
   집계 한 방으로 끝내는 가벼운 버전(무거운 candidate_media.csv 재현 아님).

   propfit_media_top500(01_create_media_vocab_table.sql, 전체 모집단 Apr~May 기준 고정
   vocab)을 그대로 재사용한다 — 그래야 6월 결과(summary_note 문서의 top10 표)와 같은
   vocab 기준으로 직접 비교 가능하다.

   전제: propfit_media_top500, seed_piellaven_ad_id가 이미 있어야 함.
   ============================================================ */

WITH base AS (
    SELECT DISTINCT b.device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" b
    LEFT JOIN seed_piellaven_ad_id sd ON b.device_ifa = sd.device_ifa
    WHERE b.year = '2026' AND b.month = '03'
      AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
      AND regexp_like(CAST(b.device_ifa AS VARCHAR), '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND sd.device_ifa IS NULL
      AND CAST(b.device_geo_region AS VARCHAR) LIKE 'KR%'
      AND regexp_like(CAST(b.device_osv AS VARCHAR), '^[0-9]+$')
),
raw_visit AS (
    SELECT
        v.req_id,
        v.req_user_id,
        v.device_ifa,
        COALESCE(
            NULLIF(CAST(v.app_bundle AS VARCHAR), ''),
            NULLIF(CAST(v.site_page AS VARCHAR), '')
        ) AS media,
        CAST(from_iso8601_timestamp(CAST(v.created_at AS VARCHAR)) AT TIME ZONE 'Asia/Seoul' AS timestamp) AS ts
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" v
    JOIN base ON v.device_ifa = base.device_ifa
    JOIN propfit_media_top500 r
      ON COALESCE(NULLIF(CAST(v.app_bundle AS VARCHAR), ''), NULLIF(CAST(v.site_page AS VARCHAR), '')) = r.media
    WHERE v.year = '2026' AND v.month = '03'
      AND v.req_user_id IS NOT NULL AND trim(CAST(v.req_user_id AS VARCHAR)) <> ''
      AND CAST(v.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (v.device_lmt IS NULL OR CAST(v.device_lmt AS VARCHAR) <> '1')
),
flagged AS (
    SELECT
        device_ifa,
        media,
        ts,
        req_id,
        LAG(media) OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_media,
        LAG(ts)    OVER (PARTITION BY req_user_id ORDER BY ts, req_id) AS prev_ts
    FROM raw_visit
),
deduped AS (
    SELECT device_ifa, media
    FROM flagged
    WHERE prev_media IS NULL
       OR prev_media <> media
       OR date_diff('second', prev_ts, ts) >= 1800
),
qualified AS (
    SELECT device_ifa
    FROM deduped
    GROUP BY device_ifa
    HAVING COUNT(*) >= 5
),
qualified_visits AS (
    SELECT DISTINCT d.device_ifa, d.media
    FROM deduped d
    JOIN qualified q ON d.device_ifa = q.device_ifa
),
total AS (
    SELECT COUNT(*) AS n FROM qualified
)
SELECT
    qv.media,
    COUNT(DISTINCT qv.device_ifa) AS visitors,
    (SELECT n FROM total) AS candidate_n,
    ROUND(CAST(COUNT(DISTINCT qv.device_ifa) AS DOUBLE) / (SELECT n FROM total) * 100, 2) AS visitor_pct
FROM qualified_visits qv
GROUP BY qv.media
ORDER BY visitors DESC
LIMIT 30;
