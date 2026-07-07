-- I1. adcampaign 테이블이 우리 기간(2026-06)의 실제 cmp_no와 관련 있는 테이블인지 확인
-- H1 샘플은 2024년 초 테스트 캠페인만 보였음 - 우리 cmp_no(10090~10120)가 실제로 존재하는지 직접 확인

SELECT count(*) AS total_rows, min(cmpno) AS min_cmpno, max(cmpno) AS max_cmpno,
       min(regdt) AS min_regdt, max(regdt) AS max_regdt
FROM "ptbwa-metadata".adcampaign;

SELECT *
FROM "ptbwa-metadata".adcampaign
WHERE cmpno IN (10090,10092,10115,10116,10117,10118,10119,10120);
