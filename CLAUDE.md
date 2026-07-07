# CLAUDE.md

`addi_data_embedding` 저장소에서 작업할 때 참고할 프로젝트 컨텍스트.

## 프로젝트 목표

특정 광고(cmp_no)에 관심 있는 사용자(디바이스) 리스트를 뽑고, 나아가 아직 postback(전환)이
없는 신규 유저 중 과거 관심 유저와 행동이 비슷한 유저를 임베딩 유사도로 찾아내는 것.

- **규칙 기반 티어 추출** (완료): `querys/audience_list_extraction/` — bid/postback 로그로
  T1(노출)~T4(완료) 티어를 매기고 관심 유저 리스트를 뽑는다. 설계 결정은
  `docs/audience_list_project.md` 참고.
- **임베딩 기반 유사 오디언스 탐색** (진행 중): `querys/audience_embedding/` — addi 데이터로
  유저 임베딩을 만든다. 모델 코드는 이 repo가 아니라 별도 저장소
  `C:\Users\data\workspace\user-to-ad-encoder`에 있고(스키마만 맞으면 그대로 재사용 가능),
  이 repo는 그 코드가 기대하는 컬럼 계약에 맞춘 SQL만 만든다. 설계/학습 계획은
  `docs/audience_embedding_plan.md` 참고.

## 현재 단기 목표

**4~5월 addi bid log + addi postback log로 임베딩 모델을 학습 → 6월 신규 유저 대상으로
임베딩 거리를 계산한다.** 실행 계획은 `docs/audience_embedding_plan.md` §7 참고.

## 데이터를 얻는 방법 (이 repo에는 Athena 접근 권한이 없음)

1. 필요한 데이터가 있으면 SQL을 `querys/<주제별 폴더>/`에 파일로 작성한다 (파일 하나에 쿼리
   하나, 번호+설명 이름).
2. 사용자가 그 SQL을 AWS Athena 콘솔에서 직접 실행하고 결과를 CSV로 받는다.
3. 사용자가 그 CSV를 `sample_data/<대응 폴더>/`에 올려주면, 그때 읽고 해석한다.
4. Athena 에러 메시지나 CSV를 사용자가 붙여넣으면, 원인을 파악해 해당 SQL 파일을 직접
   고친다 — 데이터를 직접 조회할 수 없으므로 항상 이 왕복으로 진행한다.

## 규칙

- **Athena/Glue 타입 주의**: CSV 기반 외부 테이블인데도 Glue 크롤러가 숫자처럼 보이는 컬럼을
  `bigint`/`double`로 추론해둔 경우가 많다. 문자열 함수(`trim`, `regexp_like`, `LIKE`, `||`)를
  쓰기 전엔 항상 `CAST(col AS VARCHAR)`로 감싼다. `imp_deals_array`/`ext_billing_id`처럼
  실제 array/row 타입인 컬럼은 `UNNEST`/`any_match`/`contains`로 다뤄야지 문자열 비교로
  다루면 안 된다.
- **기간 필터**: `addi_bid_log_flatten`/`addi_postback_log` 등 로그 테이블은 항상
  `year`/`month`/`day` 파티션으로 필터링한다. 기본 파일럿 기간은 `2026-06-01~06-07`. 관련된
  여러 쿼리(bid/postback 페어 등)는 기간을 서로 동일하게 맞춘다.
- **컴플라이언스 필터 (오디언스 추출/임베딩 공통 필수)**: `req_ext_allow_user_data_collection = '1'`
  인 로그만 포함(NULL/미채움은 보수적으로 제외 — 사용자 확정 정책), `device_lmt = '1'`(옵트아웃)
  디바이스는 제외. 근거는 `docs/audience_list_project.md` 참고.
- **식별자**: 광고 식별자는 `cmp_no`(+`ag_no`)를 쓴다 — `addi_advertisement.adspid`와는
  매핑이 없음(전수 조사로 확인됨, `querys/audience_list_discovery/_archived/` 참고). 유저
  식별자는 `device_ifa`(=`postback_log.ifa`, 100% 동일)가 기본 키, `req_user_id`는 보조 키.
- **addi_bid_log_flatten은 앱(CTV/Android TV) 전용 인벤토리**: `site_page`/`site_content_genre`/
  `site_content_language`/`device_connectiontype`/`device_pxratio` 컬럼이 없다(형제 테이블
  `abi_bid_log_flatten`에는 있음). 다른 프로젝트 SQL을 이식할 때 컬럼 존재 여부를
  `sample_data/raw/`의 실제 헤더로 먼저 확인한다.
- **쿼리 정리**: 가설을 검증하다 결론이 나서(매핑 없음 확인, 방향 폐기 등) 더 재실행할 일이
  없는 쿼리는 지우지 않고 `_archived/` 하위 폴더로 옮기고, 상위 README에 결론과 반영된 곳을
  남긴다.

## 문서

- `docs/data_schema.md` — 원본 4개 테이블 스키마
- `docs/data_validation_report.md` — 데이터 정합성 검증 결과
- `docs/audience_list_project.md` — 규칙 기반 T1~T4 관심 유저 리스트 설계/파일럿 결과
- `docs/audience_embedding_plan.md` — 임베딩 기반 유사 오디언스 설계 + 학습 계획
