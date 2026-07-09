-- ============================================================
-- 01_conv_web_schema_discovery.sql
-- 목적: "prod_addi_conv".raw_conv_web / raw_conv_web_imp 스키마를 처음 확인한다 — 이 저장소는
--       이 두 테이블을 아직 한 번도 조회한 적이 없어 컬럼명/타입을 모른다(mall_ip만 사용자가
--       확인해줌). 여기서 확인한 컬럼명(특히 타임스탬프, 파티션 컬럼, mall_ip 실제 타입)을
--       바탕으로 이후 매칭 쿼리(전환 라벨 생성)를 작성한다.
-- 다음 단계: 이 결과(컬럼 목록)를 보고 02/03(샘플 로우), 04/05(row count)를 확인한 뒤,
--       실제 postback↔conv_web IP 매칭 쿼리를 작성한다.
-- ============================================================

SELECT table_name, ordinal_position, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'prod_addi_conv'
  AND table_name IN ('raw_conv_web', 'raw_conv_web_imp')
ORDER BY table_name, ordinal_position;
