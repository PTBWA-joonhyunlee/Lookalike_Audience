/* ============================================================
   06b_create_candidate_table_media.sql (seed, 2026-07-31 신규)
   목적: media_sequence(SASRec) 임베딩/스코어링 전용 "신규 후보" device_ifa 목록을 새로
   만든다 — 06_create_candidate_table.sql(candidates_202606, segment 매칭 기준)과는
   별개의 독립 테이블(candidates_202606_media)이다. 기존 테이블/쿼리는 건드리지 않는다.

   배경: 기존 candidates_202606(segment 매칭 기준, 664,684명) 중 media_sequence 임베딩이
   실제로 있는 건 191,520명(28.8%)뿐이었다(embedding/media_sequence/config.MIN_SEQ_LEN=5
   미만 제외 — eda/docs/20260731_segment_media_combined_비교.md 참고). 이 쿼리는 segment
   매칭 여부와 무관하게, "6월에 seed에 없고 top500 미디어를 30분 재방문 dedup 기준 5회
   이상 방문한" 유저를 처음부터 후보로 정의해서, media 단독/combined 스코어링에 쓸 수
   있는 후보 모집단 자체를 넓혀보려는 목적이다(기존 28.8%보다 커질지, 비슷할지는 이
   쿼리 결과로 확인해야 함 — segment 없는 유저도 여기 포함될 수 있어 기존 후보와 완전히
   겹치지는 않는다).

   dedup 로직(30분 재방문 제외, req_user_id 파티션)은 04b/05b/07b_*_media.sql /
   embedding/media_sequence/build_features.py와 동일한 기준(top500 미디어, 5회 이상)을
   맞췄다 — 그래야 이 후보 전원이 media_sequence 추론에서 실제로 임베딩을 받는다.

   전제: 03_create_media_vocab_table.sql로 propfit_media_top500이 이미 만들어져 있어야 함.

   **다음 단계(아직 안 만듦)**: 이 테이블이 확정되면 07a/07b/07c와 같은 패턴으로
   profile/media/segment 추출 쿼리를 이 테이블 기준으로 새로 만들어야 한다(예:
   07d_media_candidate_profile.sql 등) — 지금은 후보 목록 자체만 우선 만든다.
   ============================================================ */

CREATE TABLE candidates_202606_media
WITH (format = 'PARQUET')
AS
WITH base AS (
    SELECT DISTINCT b.device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten" b
    LEFT JOIN seed_piellaven_ad_id sd ON b.device_ifa = sd.device_ifa
    WHERE b.year = '2026' AND b.month = '06'
      AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
      AND regexp_like(CAST(b.device_ifa AS VARCHAR), '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
      AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
      AND sd.device_ifa IS NULL
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
    WHERE v.year = '2026' AND v.month = '06'
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
    SELECT device_ifa
    FROM flagged
    WHERE prev_media IS NULL
       OR prev_media <> media
       OR date_diff('second', prev_ts, ts) >= 1800
)
SELECT device_ifa
FROM deduped
GROUP BY device_ifa
HAVING COUNT(*) >= 5;
