/* ============================================================
   05_create_lal_je_table.sql (seed, je lookalike 스코어링 결과 등록)
   목적: scoring/infer_lookalike.py --variant segment_je 출력(candidate_scores_top10pct.csv,
   device_ifa/lookalike_score 2컬럼, 헤더 있음)을 s3://ptbwa-dw/prod/LAL_je/에 올린 뒤
   Athena에서 조회 가능하게 외부 테이블로 등록한다.

   OpenCSVSerde는 컬럼을 전부 string으로만 읽는다(공식 제약) — lookalike_score를 숫자로
   쓰려면 조회 시 CAST(lookalike_score AS DOUBLE)로 감싼다(CLAUDE.md의 Athena/Glue 타입
   주의 규칙과 동일한 이유).

   실행 순서(사용자가 Athena 콘솔에서 직접 수행):
     1) candidate_scores_top10pct.csv를 s3://ptbwa-dw/prod/LAL_je/에 업로드(완료됨)
     2) 아래 DDL을 Athena 콘솔에서 실행
   ============================================================ */

CREATE EXTERNAL TABLE lal_je (
    device_ifa string,
    lookalike_score string
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar' = ','
)
LOCATION 's3://ptbwa-dw/prod/LAL_je/'
TBLPROPERTIES ('skip.header.line.count' = '1');
