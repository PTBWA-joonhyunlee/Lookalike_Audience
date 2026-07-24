-- ============================================================
-- 03_user_segments.sql (propfit)
-- 목적   : skp의 유저별 세그먼트 멤버십(관심사 세그먼트 ID 집합)을 뽑는다.
-- 스코프 : 라벨/지도학습 없이 피처 설계만 검토(2026-07-23 확정).
-- 소스   : "propfit"."skp" — DB/테이블명은 샘플 CSV 파일명 추정치, 실제 카탈로그와
--          다르면 고칠 것.
-- ID 공간 확인됨(00_id_mapping_check.sql 결과, 2026-07-23): skp.ad_id는 ptbwa_skb.ad_id와
--          매칭되고(제외한 깨진 파티션 빼고 스캔 시 수십억 건 매칭 vs platform_ad_id
--          기준은 66건뿐 — 노이즈 수준), ptbwa_skb.ad_id는 abi_bid_log_flatten.device_ifa와
--          같은 공간(사용자 제공 원본 쿼리 전제)이므로 skp.ad_id는 device_ifa와 곧바로
--          같은 공간이다. 그래서 이전 버전에 넣었던 ptbwa_skb 경유 크로스워크(platform_ad_id
--          거치는 것)는 필요 없다 — skp.ad_id를 device_ifa로 바로 alias한다.
--          (참고: abi_bid_log_flatten.device_ifa ↔ ptbwa_skb.ad_id 자체는 이번 진단으로
--          검증된 게 아니라 사용자 제공 원본 쿼리를 그대로 전제한 것 — 실제 bid log 쪽
--          커버리지는 별도 확인 필요, device_ifa가 abi 샘플 10행 중 2건만 채워져 있었음.)
-- id_type: skp 샘플엔 숫자 '2'만 보였다. ptbwa_tg는 문자열 'ADID'로 표기 — 같은 의미
--          (Android 광고 ID)인지 매핑을 확인해야 한다. 임의로 '2' = 'ADID'라고 가정하고
--          썼으니, 실제 코드표(1=IDFA, 2=ADID 등)가 있으면 그걸로 교체할 것.
-- 기간   : skp는 스냅샷 성격 테이블이라(01_user_profile.sql의 ptbwa_tg/ptbwa_skb와 동일
--          취급) year/month로 좁히지 않고 유저(ad_id)별 최신 파티션 1건만 남긴다. 대신
--          00_id_mapping_check.sql에서 이미 확인한 대로 year=2024/month=12/day=31 파티션의
--          .tmp 파일이 깨져 있어(HIVE_CURSOR_ERROR) 그 파티션만 명시적으로 제외한다.
--          ⚠ 여기서 year='2026' 같은 기간 필터를 다시 넣지 말 것 — skp 샘플/진단 결과 모두
--          2024년대 데이터만 확인됐고, 2026년 필터를 걸면 "세그먼트가 없어서"가 아니라
--          "기간이 안 맞아서" 0행이 나오는 걸 세그먼트 자체가 없는 것으로 착각하게 된다.
-- segments 포맷: 세미콜론 구분 숫자 ID 문자열(예: "13780;19017;19020").
-- 세그먼트 카테고리 매핑 발견(2026-07-23): data/sample/세그먼트_카테고리.csv(1,050행,
--          Athena 테이블 아님 — 로컬 정적 참조 파일)에 세그먼트 ID → 카테고리 경로
--          (Depth1/2/3)+이름이 있다(예: 26455 = "인구통계>성별(모델링)>여성(High)").
--          skp 샘플의 세그먼트 ID가 실제로 이 매핑에 존재함을 확인했다.
-- 임베딩 방식 재검토(2026-07-23, 카테고리 매핑 발견 반영): 이전엔 "세그먼트 ID가 순서
--          없는 opaque 코드라 사전학습 BERT가 못 붙는다"고 봤는데, 실제로는 각 ID에
--          읽을 수 있는 한국어 카테고리 경로 텍스트가 있으므로 두 방식을 다 검토할 만하다.
--            (a) EmbeddingBag(mean/sum): 세그먼트 ID를 그대로 학습 가능한 lookup 임베딩 +
--                풀링. 구현 간단, 기존 media_sequence.content_genre 처리와 동일 패턴.
--            (b) 사전학습 한국어 문장임베딩(예: ko-sroberta/KoSimCSE) + mean pooling:
--                세그먼트 ID를 카테고리 경로 텍스트로 변환(로컬 매핑 파일로 조인, SQL/Athena
--                불필요) 후 문장임베딩을 뽑아 유저별로 평균 — "SUV"와 "대형차"처럼 텍스트
--                의미가 가까운 세그먼트끼리 사전학습 지식으로 유사하게 인코딩되는 이점이
--                있어 (a)보다 데이터가 적을 때 일반화가 나을 수 있다.
--          어느 쪽이 나은지는 실험 필요 — 이번 스코프(피처 설계 검토) 밖이며, 카테고리
--          매핑은 로컬 CSV라 여기 SQL과는 별개로 embedding 코드에서 직접 로드하면 된다.
--          부가 발견: "인구통계>성별(모델링)>여성/남성(High/Low)" 세그먼트는 ptbwa_tg의
--          gender_code(선언/매칭 기반)와 별개로 모델링된 성별 신호라 교차검증 피처로도
--          쓸모 있어 보인다.
-- ============================================================

WITH segments_latest AS (
    SELECT
        ad_id AS device_ifa,
        CAST(segments AS VARCHAR) AS segments,
        year, month, day,
        ROW_NUMBER() OVER (
            PARTITION BY ad_id
            ORDER BY year DESC, month DESC, day DESC
        ) AS rn
    FROM "propfit"."skp"
    WHERE NOT (year = '2024' AND month = '12' AND day = '31')   -- 깨진 .tmp 파티션만 제외(기간 자체는 좁히지 않음)
      AND CAST(id_type AS VARCHAR) = '2'   -- ← ADID로 추정(ptbwa_tg의 'ADID' 표기와 매핑 확인 필요).
                                            --   id_type이 숫자로 보여 Glue가 bigint로 추론했을
                                            --   가능성이 높아 CAST 없이 문자열 비교하면 TYPE_MISMATCH로 죽는다.
      AND ad_id IS NOT NULL AND trim(CAST(ad_id AS VARCHAR)) <> ''
)
SELECT
    device_ifa,
    segments,   -- 세미콜론 구분 문자열 — 하류(Python)에서 split(';')으로 배열화 후 임베딩 입력
    year, day AS snapshot_day
FROM segments_latest
WHERE rn = 1;
