-- D8. postback_log.log_type 값 종류와 분포 (예상치 못한 신규/오타 이벤트 타입 탐지용)
SELECT log_type, count(*) AS cnt
FROM "prod-ptbwa-dw".addi_postback_log
WHERE year = '2026' AND month = '06' AND day BETWEEN '01' AND '07'
GROUP BY log_type
ORDER BY cnt DESC;
