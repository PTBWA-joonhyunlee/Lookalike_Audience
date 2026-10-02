/* ============================================================
   01_create_seed_table_madid.sql (seed, madid 신규 seed 등록 —
   pipeline/generate_seed_queries.py register --source-table로 자동 생성)
   목적: S3 CSV가 아니라 이미 Glue/Athena에 있는 테이블 "dev-ptbwa-da"."db_m_adid"(adid 컬럼)을
   이후 쿼리가 기대하는 seed_madid(device_ifa string) 이름으로 노출하는 뷰를 만든다 —
   데이터를 복사하지 않는다. 이 뷰를 만든 뒤 eda/queries/id_space_check/20_seed_madid_id_space_check.sql를 실행해 ID 공간을 확인할 것.
   ============================================================ */

CREATE OR REPLACE VIEW "prod-ptbwa-dw".seed_madid AS
SELECT CAST(adid AS VARCHAR) AS device_ifa
FROM "dev-ptbwa-da"."db_m_adid";
