/* ============================================================
   01_create_seed_table.sql (seed, 구 propfit/seed_lookalike/00_create_seed_table.sql)
   목적: data/seed/00_피엘라벤_seed.csv(device_ifa 1,518,101행, 외부 CRM/3rd-party 소스 —
         2026-07-29 확인: 이 프로젝트 로그 테이블과 무관하게 확보된 리스트, ab_postback_log로
         재현/검증 불가)를 Athena에서 조인 가능하게 외부 테이블로 등록한다.

   데이터 정제 완료(2026-07-29): 원본 CSV 1,518,104행 중 UUID 형식이 아닌 3행
   ("[DEVICE_ADI", "{PSID}", "platform_ad_id" — 여러 추출 배치를 이어붙이며 남은 헤더
   파편으로 추정)을 로컬에서 제거해 1,518,101행만 남겼다(정제 검증 후 백업 삭제됨).

   실행 순서(사용자가 Athena 콘솔/S3 콘솔에서 직접 수행 — 이 repo는 Athena 접근 권한 없음):
     1) data/seed/00_피엘라벤_seed.csv(정제됨)를 S3에 업로드한다(예: s3://ptbwa-dw/prod/seed_piellaven/).
        경로는 팀 S3 버킷 컨벤션에 맞춰 바꿔도 된다 — 아래 LOCATION만 그에 맞게 수정.
     2) 아래 DDL을 Athena 콘솔에서 실행한다.
     3) 01_seed_coverage_check.sql로 커버리지를 확인한다.

   주의: 이 파일은 CREATE 문 앞에 안내를 붙이는 블록 주석(/* */)을 쓴다 — 줄(--) 주석은
   줄바꿈이 사라진 채로 실행되면(콘솔 붙여넣기/스크립트 실행 방식에 따라 발생 가능) 뒤에
   오는 CREATE TABLE 문 전체를 주석으로 삼켜버려 "cannot recognize input near '<EOF>'"
   에러가 난다 — 실제로 2026-07-29에 이 파일에서 이 문제가 발생해 블록 주석으로 바꿨다.
   ============================================================ */

CREATE EXTERNAL TABLE seed_piellaven (
    device_ifa string
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar' = ','
)
LOCATION 's3://ptbwa-dw/prod/seed_piellaven/';
