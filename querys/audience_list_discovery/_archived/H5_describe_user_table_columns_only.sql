-- H5. user 테이블 - 컬럼 구조만 우선 확인 (개인정보 가능성 있어 샘플 행 조회는 보류)
-- reguserid/moduserid 값들이 이전에 "142","146" 같은 작은 정수였던 것으로 보아
-- 내부 운영자(어드민) 계정 테이블일 수도, 실제 소비자 프로필일 수도 있습니다.
-- 컬럼명을 보고 어떤 성격인지(내부 직원 vs 광고 대상 소비자) 먼저 판단한 뒤
-- 필요하면 별도로 샘플 조회 여부를 다시 논의하겠습니다.
DESCRIBE "ptbwa-metadata".user;

SELECT count(*) AS row_cnt FROM "ptbwa-metadata".user;
