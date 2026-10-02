# CLAUDE.md

`Lookalike_Audience` 저장소에서 작업할 때 참고할 프로젝트 컨텍스트. SQL/문서와 Python 모델
코드가 같은 저장소에 있다. 실행 방법은 [`README.md`](README.md)와 각 트랙 폴더의 README
참고, 이 문서는 작업 시 지켜야 할 규칙 위주.

## 프로젝트 목표

propfit 소스(`abi_bid_log_flatten` bid log + `propfit.skp` 세그먼트)에서, 외부 브랜드 seed
리스트(현재: 피엘라벤)와 비슷한 신규 유저를 임베딩 기반으로 찾아내는 것 — [`lookalike/`](lookalike/README.md)
트랙. skp 세그먼트 임베딩만 쓴다(피처는 segment 단독).

이전에는 addi(`addi_bid_log_flatten`/`addi_postback_log`, cmp_no 캠페인 postback→mall IP
매칭 전환) 소스로 시작한 별도 트랙이 있었다 — 2026-07-30에 이 트랙과 그 코드/쿼리/문서를
전부 삭제했다(propfit 소스로 갈아탐, 필요하면 git 히스토리 참고). postback 로그 기반 트랙
(placeholder였던 `postback/`)과 media(방문 앱/사이트 시퀀스 임베딩) 하위 트랙도
2026-08-26에 전부 삭제했다. 2026-10-02에는 브랜드별 일회성 쿼리/문서(seed별 SQL, 멀티라벨, 콘솔 왕복용
쿼리 생성기, `eda/queries/`, `summary_note/`)를 정리하고 `seed/`를 `lookalike/`로 바꿨다(전부 git 히스토리에 있음).

## 폴더 구조

```
lookalike/  seed 기반 신규 유저 룩어라이크 — pipeline/(Athena 실행기)·queries/templates·embedding/train/inference/scoring
config/     IAM 정책 JSON, 학습 설정 예시, AWS 키(LAL_accessKeys.csv — git 제외)
eda/        진단·EDA 결과 문서(docs/) — ID 공간 크로스워크, 표본 버그 등 규칙의 근거
data/       쿼리 결과 CSV / 임베딩 / 모델 아티팩트(git 추적 안 됨)
```

`lookalike/`는 독립 작업 루트다 — 그 폴더로 `cd`한 뒤 파이썬을 실행한다(`.venv`는
저장소 루트에 하나, 상대 경로로 참조). 새 트랙 폴더를 만들 때도 이 구조(queries/lib +
번호 매긴 파이프라인 SQL, embedding/train/inference, docs/README.md)를 따른다.

## 데이터를 얻는 방법

**2026-10-02부터 Athena/S3를 boto3로 직접 호출할 수 있다**(`lookalike/pipeline/athena.py`, 자격증명은
`config/LAL_accessKeys.csv` — git 제외, 값 출력 금지, IAM 정책은 `config/iam/`). 신규 seed 시나리오는
`lookalike/pipeline/run_seed_scenario1.py`가 전부 자동으로 돌린다(경로 규칙: `lookalike/pipeline/paths.py`,
로컬 `data/`와 `s3://ptbwa-dw/prod/lookalike/`가 같은 상대 경로). 테이블은 영구 생성하지 않는다 —
seed 목록은 임시 외부 테이블(`dev-ptbwa-da._tmp_lookalike_*`, 끝나면 DROP), 결과는 UNLOAD로 S3에
내보낸 뒤 다운로드. 비용이 큰 쿼리(후보 추출 등)를 임의로 실행하지 말고 사용자 요청이 있을 때만
돌린다. 실행기가 못 하는 쿼리(진단/EDA 등)는 SQL을 `lookalike/queries/`에 파일로 작성해 사용자가
Athena 콘솔에서 돌리게 하고(파일 하나에 statement 하나), 결과 CSV를 `data/`에 받아 해석한다.

## 규칙

- **Athena/Glue 타입 주의**: CSV 기반 외부 테이블인데도 Glue 크롤러가 숫자처럼 보이는 컬럼을
  `bigint`/`double`로 추론해둔 경우가 많다. 문자열 함수(`trim`, `regexp_like`, `LIKE`, `||`)를
  쓰기 전엔 항상 `CAST(col AS VARCHAR)`로 감싼다.
- **Athena 쿼리 작성 시 주석은 `/* */` 블록 주석을 쓴다**: `--` 줄 주석은 실행 과정에서
  줄바꿈이 사라지면(콘솔 붙여넣기/스크립트 실행 방식에 따라 발생 가능) 뒤에 오는 SQL 문
  전체를 삼켜 `cannot recognize input near '<EOF>'` 파싱 에러가 난다(2026-07-29 실제 발생).
- **해시 기반 표본 추출은 부호 없는 해시를 쓴다**: Trino의 `mod()`는 피연산자 부호를
  따라가는데 `xxhash64`/`from_big_endian_64`는 부호 있는 BIGINT를 반환한다 —
  `mod(hash,N)<K` 형태로 쓰면 음수 전부가 통과해 의도한 비율의 약 2배가 뽑힌다(2026-07-30
  실제 발생, 0.5% 표본이 ~50%로 나옴 — `eda/docs/sampling_bugs.md` 참고). `crc32`(부호
  없음) 또는 `mod(hash,N)=0` 형태(부호 무관)를 쓸 것.
- **기간 필터**: 로그 테이블(`abi_bid_log_flatten` 등)은 항상 `year`/`month`/`day` 파티션으로
  필터링한다. 학습(pool/seed)과 스코어링 대상(후보) 기간은 서로 겹치지 않게 분리한다 —
  실행기가 `data/pools/<pool_id>/pool_spec.json`의 학습 기간과 후보 `--period`가 겹치면 거부한다
  (기본 pool은 2026-04~05).
- **컴플라이언스 필터 (오디언스 추출/임베딩 공통 필수)**: `req_ext_allow_user_data_collection = '1'`
  인 로그만 포함(NULL/미채움은 보수적으로 제외), `device_lmt = '1'`(옵트아웃) 디바이스는
  제외.
- **ID 공간이 여러 개다 — 직접 조인 전에 확인할 것**: `propfit.skp.ad_id`/`propfit.ptbwa_skb.ad_id`는
  raw GAID(UUID) 공간이지만, `ptbwa_skb.platform_ad_id`는 다른 공간이다(예: 외부에서 받은
  seed 리스트가 이 공간에 있었음, `eda/docs/id_space_crosswalk.md` 참고 — 직접
  `skp.ad_id`와 조인하면 매칭이 거의 0이 나오는데도 원인을 모르고 넘어가기 쉽다).
  `abi_bid_log_flatten.device_ifa`도 대소문자가 섞여 있다(15~25%가 대문자) — 단, 실측
  결과 대소문자 자체는 매칭률에 유의미한 영향을 주지 않았다(`eda/docs/sampling_bugs.md`
  참고, 그래도 원인 불명의 낮은 매칭률을 만나면 먼저 의심해볼 것). 새 ID 필드를 조인할 땐
  값 포맷(길이/정규식/샘플)을 직접 찍어보고 확인한다 — 매칭 건수만으로 "같은 공간"이라고
  추론하지 않는다.
- **식별자**: 유저 식별자는 `device_ifa`가 기본 키, `req_user_id`는 보조 키. 새 소스를
  붙일 때 이 둘 중 뭐가 진짜 안정적인 디바이스 키인지 확인할 것(위 ID 공간 규칙 참고).
- **쿼리 정리**: 실행기가 쓰는 쿼리 템플릿(`lookalike/queries/templates/`)만 저장소에 둔다. 한 번 쓰고 끝난
  진단/EDA 쿼리는 결론을 `eda/docs/`에 남기고 쿼리 파일은 두지 않는다(필요하면 git 히스토리).
- **문서 정리**: 각 트랙의 `docs/README.md`는 "지금 어떻게 실행하고 뭐가 나오는지" 위주로
  간결하게 유지한다. 상세 조사 과정이나 지나간 의사결정 서술(왜 그렇게 설계했는지, 버그를
  어떻게 찾았는지)은 `eda/docs/`에 둔다.
- **실험 기록**: 데이터 검증/재학습/백테스트 등 실험을 돌릴 때마다 결과를 `eda/docs/`
  (또는 해당 트랙 `docs/`)에 남긴다. 실험 하나당 파일 하나 — 이전 실험 파일에 새 실험
  결과를 덧붙이지 않는다.

## 문서

- [`README.md`](README.md) — 저장소 전체 구조 개요
- [`lookalike/README.md`](lookalike/README.md) — 실행 방법(시나리오 1/2) + 폴더 구조
- [`eda/docs/README.md`](eda/docs/README.md) — 진단/EDA 인덱스(무엇을 왜 조사했는지)
