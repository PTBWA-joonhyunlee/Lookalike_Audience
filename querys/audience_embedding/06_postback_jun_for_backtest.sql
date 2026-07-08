-- ============================================================
-- 06_postback_jun_for_backtest.sql
-- 목적   : 스코어링 결과(04/05로 뽑은 6월 신규 유저) 백테스트용 — 2026-06월 postback을
--          device_ifa별 최고 도달 tier(T1~T4, J1/03과 동일한 log_type 기준)로 미리 집계해서
--          내려준다. `evaluation/backtest.py`(user-to-ad-encoder)가 이 결과를 04/05 스코어링
--          결과와 대조해 lift를 계산한다. 티어 정의(log_type→숫자 매핑)는 addi 도메인 지식이라
--          여기 SQL에 두고, Python 쪽(evaluation/backtest.py)은 범용 라벨/스코어 대조만 한다.
-- 범위   : 컴플라이언스 필터 없음 — 이미 04/05에서 동의 유저만 스코어링 대상으로 걸러뒀으므로,
--          여기서는 그 유저들의 실제 전환 이력만 조회하면 된다(postback 자체는 필터링 안 함).
-- ============================================================

SELECT
  ifa,
  max(
    CASE log_type
      WHEN 'i'         THEN 1
      WHEN 'v_start'    THEN 2
      WHEN 'v_firstQ'   THEN 3
      WHEN 'v_mid'      THEN 4
      WHEN 'v_thirdQ'   THEN 5
      WHEN 'v_complete' THEN 6
      ELSE 0
    END
  ) AS max_tier
FROM "prod-ptbwa-dw".addi_postback_log
WHERE year = '2026' AND month = '06'
  AND ifa IS NOT NULL AND trim(CAST(ifa AS VARCHAR)) <> ''
GROUP BY ifa;
