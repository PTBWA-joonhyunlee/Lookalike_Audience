/* ============================================================
   06_create_table_seed_madid_top40.sql (seed, madid 룩어라이크 결과 전달용 테이블)
   목적: data/models/lookalike_classifier_madid/candidate_scores_top40pct.csv
   (device_ifa, lookalike_score — 후보 8,769,975명 중 스코어 상위 40%, 3,507,991행, 헤더 있음)를
   S3에 올린 뒤 Athena 외부 테이블로 등록한다.

   실행 순서(이 repo는 AWS 접근 권한이 없어 사용자가 직접 수행):
     1) 위 CSV를 S3에 업로드한다(아래 LOCATION은 폴더 경로 — 파일 하나만 넣을 것):
        aws s3 cp candidate_scores_top40pct.csv s3://ptbwa-dw/prod/seeds/seed_madid_top40/
        (경로가 다르면 LOCATION만 그에 맞게 수정)
     2) 아래 DDL을 Athena 콘솔에서 실행한다 — 테이블명이 dev-ptbwa-da.seed_madid_top40 이라
        데이터베이스 이름까지 붙였다. DDL(CREATE EXTERNAL TABLE)은 Hive 문법이라 하이픈이 든
        이름은 큰따옴표가 아니라 백틱(`)으로 감싸야 한다(큰따옴표는 SELECT용 Trino 문법 —
        2026-10-01 "mismatched input 'EXTERNAL'" 에러 발생).

   주의: lookalike_score는 pos_weight 학습 점수라 seed 간 비교용이 아니다. OpenCSVSerde는
   모든 컬럼을 string으로 읽으므로 점수를 숫자로 쓰려면 CAST(lookalike_score AS DOUBLE).
   ============================================================ */

CREATE EXTERNAL TABLE `dev-ptbwa-da`.seed_madid_top40 (
    device_ifa string,
    lookalike_score string
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar' = ','
)
LOCATION 's3://ptbwa-dw/prod/seeds/seed_madid_top40/'
TBLPROPERTIES ('skip.header.line.count' = '1');
