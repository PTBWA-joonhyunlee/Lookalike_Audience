/* ============================================================
   01_create_seed_table_enlistee.sql (seed, enlistee 신규 seed 등록 —
   pipeline/generate_seed_queries.py가 01_create_seed_table_je.sql을 템플릿 삼아 자동 생성)
   목적: data/seed/입대예정자_adid.csv를 Athena에서 조인 가능하게 외부 테이블로 등록한다. 헤더가 있어 skip.header.line.count로 건너뛴다.

   실행 순서(사용자가 Athena 콘솔/S3 콘솔에서 직접 수행 — 이 repo는 Athena 접근 권한 없음):
     1) data/seed/입대예정자_adid.csv를 S3에 업로드한다: s3://ptbwa-dw/prod/seeds/seed_enlistee/
        (경로가 다르면 아래 LOCATION만 그에 맞게 수정)
     2) 아래 DDL을 Athena 콘솔에서 실행한다.
     3) eda/queries/id_space_check/17_seed_enlistee_id_space_check.sql로 이 seed의 device_ifa가 어떤 ID 공간에 있는지 확인한다(raw GAID인지,
        크로스워크가 필요한지) — 이 확인 전에는 02_create_seed_ad_id_table_enlistee.sql을
        작성/실행하지 말 것. 결과 한 줄을 받으면
        `pipeline.generate_seed_queries resolve --seed-name enlistee --matches ...`로
        넘겨 이후 쿼리를 자동 생성한다.

   주의: 이 파일은 CREATE 문 앞에 안내를 붙이는 블록 주석(／＊ ＊／)을 쓴다 — 줄(--) 주석은
   줄바꿈이 사라진 채로 실행되면(콘솔 붙여넣기/스크립트 실행 방식에 따라 발생 가능) 뒤에
   오는 CREATE TABLE 문 전체를 주석으로 삼켜버려 "cannot recognize input near '<EOF>'"
   에러가 난다(2026-07-29 seed_piellaven 등록 때 실제 발생).
   ============================================================ */

CREATE EXTERNAL TABLE seed_enlistee (
    device_ifa string
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar' = ','
)
LOCATION 's3://ptbwa-dw/prod/seeds/seed_enlistee/'
TBLPROPERTIES ('skip.header.line.count' = '1');
