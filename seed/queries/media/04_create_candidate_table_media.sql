/* ============================================================
   media/04_create_candidate_table_media.sql (seed, 2026-08-04 segment/media 트랙 분리 —
   구 06b_create_candidate_table_media.sql + 06c_sample_candidate_table_media.sql 통합)
   목적: media_sequence(SASRec) 임베딩/스코어링 전용 "신규 후보" device_ifa 목록
   (candidates_202606_media_sample)을 만든다 — segment/03_create_candidate_table.sql
   (candidates_202606, segment 매칭 기준)과는 별개의, media 트랙 전용 독립 테이블이다.

   배경: segment 매칭 기준 후보(segment/03) 중 media_sequence 임베딩이 실제로 있는 건
   일부뿐이었다(embedding/media_sequence/config.MIN_SEQ_LEN=5 미만 제외 —
   eda/docs/20260731_segment_media_combined_비교.md 참고). 이 쿼리는 segment 매칭
   여부와 무관하게, "6월에 seed에 없고 top500 미디어를 30분 재방문 dedup 기준(항목
   무관 합산) 5회 이상 방문한" 유저를 처음부터 media 트랙 후보로 정의한다.

   dedup 로직(30분 재방문 제외, req_user_id 파티션)·최소 활동량 기준(5회 이상)은
   02_pool_media.sql/03_seed_media.sql/embedding/media_sequence/build_features.py와
   동일한 기준을 맞췄다 — 그래야 이 후보 전원이 media_sequence 추론에서 실제로
   임베딩을 받는다.

   전제: 01_create_media_vocab_table.sql로 propfit_media_top500이 이미 만들어져 있어야 함.

   2026-08-03 수정(region=KR/OS=Android 필터 추가): pool/candidate의 해외·iOS 트래픽이
   media 신호를 희석시킨다는 가설을 검증하기 위해 후보 모집단(base CTE) 자체를
   region=KR AND OS=Android로 제한한다.

   2026-08-03 수정(표본 비율 5%→20%→100%): 필터 후 20% 표본도 목표(약 66만 명)에 크게
   못 미쳐(160,717명뿐 — pool의 KR+Android 비율 27.77%를 근사치로 썼지만 이 population의
   실제 비율은 훨씬 낮았음), 표본 추출을 아예 없애고 필터 후 전체(804,606명)를 쓰기로
   했다.

   2026-08-04 수정(06c 통합): 별도였던 06c_sample_candidate_table_media.sql은 더 이상
   샘플링을 하지 않아(위 항목 참고) `candidates_202606_media`를 그대로 복사하기만 하는
   무의미한 단계가 됐다 — 이 파일에 통합해 바로 최종 테이블명(candidates_202606_media_sample,
   05_candidate_media.sql이 참조)으로 만든다. "_sample"이라는 이름은 역사적 이유로
   남아있을 뿐 지금은 표본이 아니라 필터 후 전체 인원이다.
   ============================================================ */

CREATE TABLE candidates_202606_media_sample
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
