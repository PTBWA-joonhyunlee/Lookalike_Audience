-- L1. abi_bid_log_flatten 구조 확인
-- addi_bid_log_flatten과 별개로 존재하는 파티션 테이블(G2에서 발견). req_user_id로 addi 쪽과
-- 매핑 가능한지, 그리고 여기에만 있는 "사용자 방문 로그"성 컬럼(세션/페이지/이벤트 등)이
-- 있는지 확인하기 위한 스키마 + 샘플 조회.

DESCRIBE "prod-ptbwa-dw".abi_bid_log_flatten;

SELECT count(*) AS row_cnt FROM "prod-ptbwa-dw".abi_bid_log_flatten;

SELECT * FROM "prod-ptbwa-dw".abi_bid_log_flatten LIMIT 5;
