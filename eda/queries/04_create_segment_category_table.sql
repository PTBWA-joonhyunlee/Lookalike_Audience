-- 2026-07-24 적재 확인됨: "prod-ptbwa-dw"."segment_category"로 조회 가능, 콤마 포함
-- segment_name(예: segment_id=49718)도 OpenCSVSerde가 정상 파싱함.
CREATE EXTERNAL TABLE segment_category (
    depth1 string,
    depth2 string,
    depth3 string,
    segment_name string,
    segment_id string
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
WITH SERDEPROPERTIES (
    'separatorChar' = ',',
    'quoteChar' = '\"'
)
LOCATION 's3://ptbwa-dw/prod/segment_category/'
TBLPROPERTIES (
    'skip.header.line.count'='1'
);