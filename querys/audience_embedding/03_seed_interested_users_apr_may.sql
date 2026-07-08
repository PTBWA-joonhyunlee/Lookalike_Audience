-- ============================================================
-- 03_seed_interested_users_apr_may.sql
-- 목적   : 임베딩 유사도 스코어링의 "시드(seed/reference)" 집합 — 2026-04~05월에 실제로
--          관심을 보인(T2 이상) 유저 리스트. 폐기된 규칙 기반 티어 추출 트랙(J1/J2, 히스토리는
--          docs/_archive/audience_list_project_full.md 참고)과 티어 판정 로직은 동일하지만
--          두 가지가 다르다:
--            1) cmp_no 필터 없음 — 특정 캠페인이 아니라 전체 캠페인 풀링 (§7 파일럿 결정,
--               docs/audience_embedding_plan.md §5/§7-3 참고. 특정 캠페인으로 좁힐 실제
--               니즈가 생기면 cmp_no 필터를 추가하면 됨)
--            2) 기간 2026-04-01~05-31 (학습 기간과 동일 — docs/audience_embedding_plan.md §7-1)
-- 출력   : req_user_id 그레인 (임베딩이 req_user_id로 키잉되므로). device_ifa는 참고용으로 같이 둠.
-- 다음 단계: 이 결과의 req_user_id들을 inference로 뽑은 04-05월 임베딩과 매칭해
--          scoring.train_supervised_lookalike로 분류기를 학습하고, 06월 신규 유저(04_05 참고)를
--          scoring.infer_supervised_lookalike로 스코어링한다(README.md §2-3 참고, 또는
--          pipeline.run_all로 한번에 실행 — README.md §2-0).
-- ============================================================

WITH bid_exposure AS (
  SELECT
    b.device_ifa,
    arbitrary(b.req_user_id) AS req_user_id,
    min(b.created_at) AS first_exposed_at,
    max(b.created_at) AS last_exposed_at,
    count(*) AS impression_cnt
  FROM "prod-ptbwa-dw".addi_bid_log_flatten b
  WHERE b.year = '2026' AND b.month IN ('04', '05')
    AND b.device_ifa IS NOT NULL AND trim(CAST(b.device_ifa AS VARCHAR)) <> ''
    AND regexp_like(CAST(b.device_ifa AS VARCHAR), '^[0-9a-fA-F-]{36}$')
    AND CAST(b.req_ext_allow_user_data_collection AS VARCHAR) = '1'
    AND (b.device_lmt IS NULL OR CAST(b.device_lmt AS VARCHAR) <> '1')
  GROUP BY b.device_ifa
),
engagement AS (
  SELECT
    p.ifa AS device_ifa,
    max(
      CASE p.log_type
        WHEN 'i'         THEN 1
        WHEN 'v_start'    THEN 2
        WHEN 'v_firstQ'   THEN 3
        WHEN 'v_mid'      THEN 4
        WHEN 'v_thirdQ'   THEN 5
        WHEN 'v_complete' THEN 6
        ELSE 0
      END
    ) AS max_tier,
    count(DISTINCT p.log_type) AS engagement_stage_cnt,  -- count(*) 대신 distinct 사용 (B2 중복 적재 영향 제거)
    max(p.created_at) AS last_engaged_at
  FROM "prod-ptbwa-dw".addi_postback_log p
  WHERE p.year = '2026' AND p.month IN ('04', '05')
    AND p.ifa IS NOT NULL AND trim(CAST(p.ifa AS VARCHAR)) <> ''
  GROUP BY p.ifa
),
scored AS (
  SELECT
    e.req_user_id,
    e.device_ifa,
    e.impression_cnt,
    e.first_exposed_at,
    e.last_exposed_at,
    g.max_tier AS max_engagement_tier,
    CASE
      WHEN g.max_tier >= 6 THEN 'T4_고관여(완료)'
      WHEN g.max_tier >= 4 THEN 'T3_중간참여'
      WHEN g.max_tier >= 1 THEN 'T2_참여시작'
      ELSE 'T1_노출만'
    END AS interest_tier,
    g.engagement_stage_cnt,
    g.last_engaged_at
  FROM bid_exposure e
  JOIN engagement g ON e.device_ifa = g.device_ifa   -- INNER JOIN: postback 이벤트가 있는 사람만
)
SELECT *
FROM scored
WHERE max_engagement_tier >= 1   -- T2 이상 (시드 집합 문턱값)
  AND req_user_id IS NOT NULL AND trim(CAST(req_user_id AS VARCHAR)) <> ''
ORDER BY max_engagement_tier DESC, engagement_stage_cnt DESC, impression_cnt DESC;
