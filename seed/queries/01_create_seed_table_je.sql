/* ============================================================
   01_create_seed_table_je.sql (seed, je 신규 seed 등록 — 01_create_seed_table.sql[피엘라벤]과
   같은 패턴)
   목적: data/seed/je_sample_adid.csv(컬럼 "ifa" 1행 헤더 + UUID 형식 device_ifa 1,923행)를
   Athena에서 조인 가능하게 외부 테이블로 등록한다.

   피엘라벤 seed(원본에 헤더 없음, 로컬에서 비-UUID 행 사전 정제)와 달리 이 CSV는 헤더
   행("ifa")이 있으므로 skip.header.line.count로 건너뛴다 — 값 정제(비-UUID 행 제거)는
   하지 않았고, 대신 02_create_seed_ad_id_table_je.sql/28_seed_je_id_space_check.sql
   쪽에서 정규식 필터로 방어한다(피엘라벤 때와 동일한 관례).

   실행 순서(사용자가 Athena 콘솔/S3 콘솔에서 직접 수행 — 이 repo는 Athena 접근 권한 없음):
     1) data/seed/je_sample_adid.csv를 S3에 업로드한다: s3://ptbwa-dw/prod/seed_je/
        (경로는 팀 S3 버킷 컨벤션에 맞춰 바꿔도 된다 — 아래 LOCATION만 그에 맞게 수정)
     2) 아래 DDL을 Athena 콘솔에서 실행한다.
     3) ../../eda/queries/id_space_check/14_seed_je_id_space_check.sql로 이 seed의 device_ifa가 어떤 ID
        공간에 있는지 확인한다(raw GAID인지, platform_ad_id라 크로스워크가 필요한지) —
        이 확인 전에는 02_create_seed_ad_id_table_je.sql을 실행하지 말 것(크로스워크 필요
        여부에 따라 그 파일의 쿼리 내용이 달라진다).

   주의: 이 파일은 CREATE 문 앞에 안내를 붙이는 블록 주석(／＊ ＊／)을 쓴다 — 줄(--) 주석은
   줄바꿈이 사라진 채로 실행되면(콘솔 붙여넣기/스크립트 실행 방식에 따라 발생 가능) 뒤에
   오는 CREATE TABLE 문 전체를 주석으로 삼켜버려 "cannot recognize input near '<EOF>'"
   에러가 난다(2026-07-29 seed_piellaven 등록 때 실제 발생).
   ============================================================ */

CREATE EXTERNAL TABLE seed_je (
    device_ifa string
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar' = ','
)
LOCATION 's3://ptbwa-dw/prod/seed_je/'
TBLPROPERTIES ('skip.header.line.count' = '1');
