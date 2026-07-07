-- I2. adgroup 테이블이 우리 기간(2026-06)의 실제 ag_no와 관련 있는 테이블인지 확인
SELECT count(*) AS total_rows, min(agno) AS min_agno, max(agno) AS max_agno,
       min(regdt) AS min_regdt, max(regdt) AS max_regdt
FROM "ptbwa-metadata".adgroup;

SELECT *
FROM "ptbwa-metadata".adgroup
WHERE agno IN (10090,10092,10115,10116,10117,10118,10119,10120);
