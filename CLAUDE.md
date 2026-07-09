# CLAUDE.md

`addi_data_embedding` 저장소에서 작업할 때 참고할 프로젝트 컨텍스트. SQL/문서 저장소였던 이
repo와 임베딩 모델 코드 저장소(`user-to-ad-encoder`)를 2026-07-08에 하나로 합쳤다 — 이제
Athena SQL(`querys/`)과 Python 모델 코드(`embedding/`, `train/`, `inference/`, `scoring/`,
`evaluation/`, `pipeline/`)가 같은 저장소에 있다. 실행 방법 전체는 [`README.md`](README.md)
참고, 이 문서는 작업 시 지켜야 할 규칙 위주.

## 프로젝트 목표

특정 광고(cmp_no)에 관심 있는 사용자(디바이스) 리스트를 뽑고, 나아가 아직 postback(전환)이
없는 신규 유저 중 과거 관심 유저와 행동이 비슷한 유저를 임베딩 유사도로 찾아내는 것
(파일럿 완료, 프로덕션 전환 전). `querys/audience_embedding/` 01~06.sql로 데이터를 만들고,
`train/`→`inference/`→`scoring/`→`evaluation/`로 학습/추론/스코어링/백테스트한다
(`pipeline.run_all`로 한번에 실행도 가능, `README.md` §2-0). 모델 구조는
`docs/model_architecture.md`, 실행 커맨드는 `README.md` 참고.

## 데이터를 얻는 방법 (이 repo에는 Athena 접근 권한이 없음)

1. 필요한 데이터가 있으면 SQL을 `querys/<주제별 폴더>/`에 파일로 작성한다 (파일 하나에 쿼리
   하나, 번호+설명 이름).
2. 사용자가 그 SQL을 AWS Athena 콘솔에서 직접 실행하고 결과를 CSV로 받는다.
3. 사용자가 그 CSV를 `data/raw/`(임베딩 파이프라인) 또는 해당 쿼리 폴더에 대응하는 위치에
   올려주면, 그때 읽고 해석한다.
4. Athena 에러 메시지나 CSV를 사용자가 붙여넣으면, 원인을 파악해 해당 SQL 파일을 직접
   고친다 — 데이터를 직접 조회할 수 없으므로 항상 이 왕복으로 진행한다.

## 규칙

- **Athena/Glue 타입 주의**: CSV 기반 외부 테이블인데도 Glue 크롤러가 숫자처럼 보이는 컬럼을
  `bigint`/`double`로 추론해둔 경우가 많다. 문자열 함수(`trim`, `regexp_like`, `LIKE`, `||`)를
  쓰기 전엔 항상 `CAST(col AS VARCHAR)`로 감싼다. `imp_deals_array`/`ext_billing_id`처럼
  실제 array/row 타입인 컬럼은 `UNNEST`/`any_match`/`contains`로 다뤄야지 문자열 비교로
  다루면 안 된다.
- **기간 필터**: `addi_bid_log_flatten`/`addi_postback_log` 등 로그 테이블은 항상
  `year`/`month`/`day` 파티션으로 필터링한다. 관련된 여러 쿼리(bid/postback 페어 등)는 기간을
  서로 동일하게 맞춘다. 임베딩 파이프라인은 학습=2026-04~05, 스코어링 대상=2026-06.
- **컴플라이언스 필터 (오디언스 추출/임베딩 공통 필수)**: `req_ext_allow_user_data_collection = '1'`
  인 로그만 포함(NULL/미채움은 보수적으로 제외 — 사용자 확정 정책), `device_lmt = '1'`(옵트아웃)
  디바이스는 제외. 근거는 `docs/_archive/audience_list_project_full.md` 참고.
- **식별자**: 광고 식별자는 `cmp_no`(+`ag_no`)를 쓴다 — `addi_advertisement.adspid`와는
  매핑이 없음(전수 조사로 확인됨). 이 때문에 `addi_business`(광고주 정보)도 유저/캠페인
  어느 쪽에도 못 붙는다(`README.md` "알려진 이슈" 참고). 유저 식별자는
  `device_ifa`(=`postback_log.ifa`, 100% 동일)가 기본 키, `req_user_id`는 보조 키.
- **addi_bid_log_flatten은 앱(CTV/Android TV) 전용 인벤토리**: `site_page`/`site_content_genre`/
  `site_content_language`/`device_connectiontype`/`device_pxratio` 컬럼이 없다(형제 테이블
  `abi_bid_log_flatten`에는 있음). 다른 프로젝트 SQL을 이식할 때 컬럼 존재 여부를 실제
  CSV 헤더로 먼저 확인한다.
- **media_sequence 임베딩의 `media` 컬럼은 `app_bundle`이 아니라 `content_genre` 대표값**이다
  — addi CTV는 app_bundle이 통신사 앱 3종뿐이라 다음-아이템 예측이 무의미해서 재정의했다
  (`docs/model_architecture.md` §2 참고). 비슷한 실수를 반복하지 않도록 새 시퀀스 피처를
  추가할 때 카디널리티를 먼저 확인한다.
- **쿼리 정리**: 가설을 검증하다 결론이 나서(매핑 없음 확인, 방향 폐기 등) 더 재실행할 일이
  없는 쿼리는 지우지 않고 `_archived/` 하위 폴더로 옮기고, 상위 README에 결론과 반영된 곳을
  남긴다.
- **문서 정리**: 이 저장소는 히스토리/의사결정 로그보다 "지금 어떻게 실행하고 뭐가 나오는지"를
  우선한다. 상세 조사 과정이나 지나간 의사결정 서술은 `docs/_archive/`에 두고, 최상위
  문서(`README.md`, `docs/*.md`)는 실행 방법과 산출물 표 위주로 간결하게 유지한다.
- **실험 기록**: 데이터 검증/재학습/백테스트 등 실험을 돌릴 때마다(한 세션에서 여러 번이면
  각각) 결과를 `docs/_archive/YYYYMMDDHHMM.md`(한국 시간 KST 기준, 실행 시각)로 남긴다.
  실험 하나당 파일 하나 — 이전 실험 파일에 새 실험 결과를 덧붙이지 않는다(같은 날이어도
  시:분까지 다르면 새 파일, 예: `202607091533.md`와 `202607091610.md`). 서로 이어지는
  실험이면 파일 상단에 이전/다음 문서를 링크로 연결한다.

## 문서

- `README.md` — 전체 파이프라인 실행 커맨드 + 산출물 위치 (가장 먼저 볼 문서)
- `docs/addi_raw_data_schema.md` — 원본(raw) Athena 4개 테이블 스키마
- `docs/audience_embedding_data_schema.md` — `querys/audience_embedding/` 01~06.sql이 뽑는
  가공된 산출물(파이프라인 입력 CSV) 스키마
- `docs/model_architecture.md` — 임베딩 모델 구조/하이퍼파라미터, fusion/스코어링 방식 비교
- `docs/output_analysis.md` — 백테스트 결과(그룹별 반응률/배율)를 비전공자도 읽을 수 있게
  설명한 문서. 새로 백테스트를 돌려 결과가 바뀌면 이 문서의 수치도 갱신할 것.
- `docs/_archive/` — 위 문서들의 상세 조사 과정/의사결정 히스토리 원본 (참고용, 갱신 안 함).
  규칙 기반 T1~T4 관심 유저 리스트(J1/J2, 폐기된 별도 트랙)의 설계/파일럿 결과도 여기
  `audience_list_project_full.md`에 남아있다.
