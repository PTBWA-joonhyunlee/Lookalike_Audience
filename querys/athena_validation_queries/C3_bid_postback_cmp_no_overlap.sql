-- C3. bid_log_flatten <-> postback_log: cmp_no 매칭 여부
-- 두 로그가 같은 캠페인 ID 체계를 쓰는지 확인
-- (샘플 10건에서는 겹치지 않았음 - 실제 데이터로 재검증 필요)
SELECT
  (SELECT count(DISTINCT cmp_no) FROM "prod-ptbwa-dw".addi_bid_log_flatten
     WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07')  AS bid_distinct_cmp_no,
  (SELECT count(DISTINCT cmp_no) FROM "prod-ptbwa-dw".addi_postback_log
     WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07')  AS postback_distinct_cmp_no,
  (SELECT count(DISTINCT b.cmp_no)
     FROM "prod-ptbwa-dw".addi_bid_log_flatten b
     JOIN "prod-ptbwa-dw".addi_postback_log p ON b.cmp_no = p.cmp_no
     WHERE b.year = '2026' AND b.month = '06' AND b.day BETWEEN '01' AND '07'
       AND p.year = '2026' AND p.month = '06' AND p.day BETWEEN '01' AND '07'
  ) AS overlapping_cmp_no;
