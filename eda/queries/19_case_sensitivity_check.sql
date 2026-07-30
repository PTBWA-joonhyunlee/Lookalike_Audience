/* ============================================================
   19_case_sensitivity_check.sql (eda, 구 09_case_sensitivity_check.sql)
   배경: 08c_candidate_segment.sql 결과(132,897명, 08a 843만 명 대비 1.6% — 일반
   모집단 기준 세그먼트 커버리지 21.8%보다 훨씬 낮음)를 조사하다가, 매칭된 device_ifa가
   전부 소문자임을 확인했다(로컬 CSV 검증) — skp.ad_id/skb.ad_id 공간이 소문자
   위주인데 abi_bid_log_flatten.device_ifa는 대소문자가 섞여 있어서(로컬 샘플 기준
   15~25%가 대문자 포함) 대소문자 구분 조인이 대문자 쪽을 조용히 누락시키고 있을
   가능성이 있다. 같은 물리 기기가 대문자/소문자 둘 다로 찍히는 건 아님을 이미
   확인했다(대문자를 소문자로 바꿔도 자연 소문자 집합과 겹침이 150만 개 중 16개뿐).

   05a_seed_profile.sql(seed → bidlog, INNER JOIN)도 같은 패턴의 조인이라 영향받을 수
   있는데, 실제 매칭분의 대문자 비율은 0.54%(6,462/1,197,069)로 낮게 나와 애매하다 —
   seed 모집단 자체가 우연히 소문자 위주 채널에 몰려있는 건지, 대소문자 문제로 실제
   매칭을 누락 중인 건지 이 쿼리로 직접 잰다. 05b(4GB)를 재작업하기 전에 먼저 확인.
   ============================================================ */

WITH bidlog AS (
    SELECT DISTINCT device_ifa
    FROM "prod-ptbwa-dw"."abi_bid_log_flatten"
    WHERE year = '2026' AND month IN ('04', '05')
      AND device_ifa IS NOT NULL AND trim(CAST(device_ifa AS VARCHAR)) <> ''
      AND CAST(req_ext_allow_user_data_collection AS VARCHAR) = '1'
      AND (device_lmt IS NULL OR CAST(device_lmt AS VARCHAR) <> '1')
)
SELECT
    (SELECT count(*) FROM seed_piellaven_ad_id) AS seed_ad_id_total,
    (SELECT count(*) FROM seed_piellaven_ad_id sd
        JOIN bidlog b ON sd.device_ifa = b.device_ifa) AS case_sensitive_match,
    (SELECT count(*) FROM seed_piellaven_ad_id sd
        JOIN bidlog b ON lower(sd.device_ifa) = lower(b.device_ifa)) AS case_insensitive_match
;
