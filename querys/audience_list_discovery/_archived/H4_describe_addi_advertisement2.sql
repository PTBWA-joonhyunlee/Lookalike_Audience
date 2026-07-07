-- H4. addi_advertisement2 구조 확인 - addi_advertisement과 어떤 차이인지(신버전/이력 테이블인지) 파악
DESCRIBE "ptbwa-metadata".addi_advertisement2;

SELECT count(*) AS row_cnt FROM "ptbwa-metadata".addi_advertisement2;

SELECT * FROM "ptbwa-metadata".addi_advertisement2 LIMIT 5;
