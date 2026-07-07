# addi 오디언스 임베딩 설계 + 학습 계획

`docs/audience_list_project.md`(규칙 기반 T1~T4 티어 리스트)에 이어지는 두 번째 트랙. 목표는
**"신규 캠페인의 bid 로그만 있고 postback(전환)이 아직 없는 유저 중, 과거 관심 유저(J2 리스트)와
행동 패턴이 비슷한 유저를 찾는" 유사도(lookalike) 기반 스코어링**이다. 규칙 기반 티어링(J1/J2)은
"이미 반응한 사람"만 잡아내는 후행 지표라, 아직 반응하지 않았지만 반응할 가능성이 높은 신규
유저를 찾으려면 별도 접근이 필요 — 그 방법으로 임베딩 유사도를 검토한다.

## 0. 핵심 결정: 기존 `user-to-ad-encoder` 코드를 그대로 재사용한다

`C:\Users\data\workspace\user-to-ad-encoder`에 이미 "유저 임베딩으로 유사 오디언스 찾기"
파이프라인이 구현돼 있다 (`abi_bid_log_flatten` 기반). 그 코드(`embedding/`, `train/`,
`inference/`)는 특정 소스에 종속되지 않고 **CSV 컬럼 계약(schema contract)에만 의존**한다 —
모델 구조도 데이터가 뭘 의미하는지 모르고 컬럼 이름/타입만 보고 동작한다.

`addi_bid_log_flatten`은 L1 조사에서 확인했듯 `abi_bid_log_flatten`과 **컬럼 구조가 사실상
동일한 OpenRTB 플랫 로그**다. 따라서:

- 새 Python 코드를 짤 필요 없이, **원본 01/02.sql의 출력 컬럼 이름/타입을 그대로 맞춘 addi
  버전 SQL**(`querys/audience_embedding/01_top500_media_visit.sql`,
  `02_user_profile.sql`)만 작성하면 기존 `embedding/user_profile`, `embedding/media_sequence`,
  `train/*.py`, `inference/*.py`를 **무수정으로 재사용**할 수 있다.
- 단, addi 데이터로 학습한 모델은 abi 모델과 **별도 아티팩트**로 저장해야 한다(`--output`/
  `--model-dir`로 분리). vocab(`vocab_media.json` 등)이 소스별로 다른 분포에서 fit되므로 abi
  모델 가중치를 addi 데이터에 그대로 쓰면 안 됨(반대도 마찬가지).

## 1. addi 버전 SQL — abi 버전과의 차이

| 항목 | abi 원본 (`user-to-ad-encoder`) | addi 버전 (이 저장소) |
|---|---|---|
| 소스 테이블 | `prod-ptbwa-dw.abi_bid_log_flatten` | `prod-ptbwa-dw.addi_bid_log_flatten` |
| 컴플라이언스 필터 | 없음 | `req_ext_allow_user_data_collection='1'` AND LMT 제외 (`docs/audience_list_project.md` 확정 정책과 동일) |
| 캠페인(cmp_no) 범위 | 필터 없음(전체) | **필터 없음(전체)** — 특정 광고 한정 X. 임베딩은 범용으로 만들고, 캠페인별 타겟팅은 다운스트림(§4)에서 처리 |
| 기간 | 2026-06-01~06-07 | 동일 (파일럿). 운영 전환 시 30~90일로 확장 권장 — 7일치는 유저당 시퀀스가 짧아 media_sequence 학습 신호가 약함 |
| 출력 방식 | `CREATE TABLE ... WITH (...) AS` (Parquet, S3 영구 테이블) | 이 프로젝트 관례대로 plain `SELECT` → Athena에서 CSV 다운로드 (파일럿 단계라 영구 테이블 불필요. 운영 전환 시 CTAS로 바꾸는 건 SQL 앞뒤만 감싸면 됨) |
| 컬럼명/타입 | 원본 그대로 | **동일** (embedding 코드 재사용을 위해 반드시 유지) + Athena 타입 방어용 `CAST(... AS VARCHAR)` 추가 (이 프로젝트에서 이미 여러 번 겪은 Glue 타입 추론 이슈 대응) |

산출 파일: `querys/audience_embedding/01_top500_media_visit.sql`,
`querys/audience_embedding/02_user_profile.sql` — 컬럼 정의는
[data-spec 문서](../../user-to-ad-encoder/docs/data-spec-audience-embedding-similarity.md) 참고
(스키마 동일하므로 새 문서 작성 안 함).

### 1-1. 실행 중 확인된 컬럼 격차 (addi_bid_log_flatten은 순수 앱 인벤토리)

실제 Athena 실행(`COLUMN_NOT_FOUND`)으로 확인됨: `addi_bid_log_flatten`에는 `abi_bid_log_flatten`에
있던 `site_page`/`site_content_genre`/`site_content_language`/`device_connectiontype`/
`device_pxratio` 컬럼이 **아예 존재하지 않는다**. abi는 앱+웹 인벤토리를 다 갖고 있지만
addi는 앱(CTV/Android TV) 인벤토리만 있는 것으로 보인다. 대응:

| 컬럼 | 처리 |
|---|---|
| `media` | `site_page` 폴백 제거, `app_bundle`만 사용 |
| `content_genre` | `site_content_genre` 폴백 제거, `app_content_genre`만 사용 |
| `language` | `site_content_language` 폴백 제거, `app_content_language`만 사용 |
| `connection_type` | 컬럼 자체가 없어 **항상 NULL로 출력** — embedding 코드와의 컬럼 계약(스키마)만 유지하고, 실제로는 `<NA>` 임베딩만 학습되는 상수(정보 없는) 피처가 됨 |
| `device_pxratio` | 위와 동일하게 항상 NULL 출력, `numeric.py`의 결측 마스킹으로 학습 손실에서 제외 — 상수 피처 |

`connection_type`/`device_pxratio`는 addi 변형에서는 사실상 죽은 피처이므로, 1차 학습 결과를
보고 아예 addi 전용 `config.py`에서 빼는 것(모델 파라미터 절약)을 고려할 수 있다 — 지금은
원본과의 컬럼 호환을 우선해 죽은 피처인 채로 남겨뒀다.

## 2. 임베딩 아키텍처 (재사용, 변경 없음)

| 트랙 | 입력 | 모델 | 학습 방식 | 차원 |
|---|---|---|---|---|
| `user_profile` | 02 결과 (유저 1행: device/지역/언어/네트워크) | Autoencoder (범주형 `nn.Embedding` + 수치형 표준화 → concat → encoder → 필드별 복원) | Self-supervised reconstruction | 64 |
| `media_sequence` | 01 결과 (유저×미디어×시각 이벤트, top500 필터 + 30분 재방문 제거) | SASRec (causal self-attention, next-item prediction) | Self-supervised next-item | 64 |

구조/하이퍼파라미터 상세는 원본 명세서 그대로 따른다 — 코드를 그대로 쓰므로 바뀌는 게 없다:
[`embedding-spec-user-profile.md`](../../user-to-ad-encoder/docs/embedding-spec-user-profile.md),
[`embedding-spec-top500-media-visit.md`](../../user-to-ad-encoder/docs/embedding-spec-top500-media-visit.md).

## 3. 학습/추론 실행 계획

`user-to-ad-encoder` 저장소의 venv에서 실행 (이 저장소는 SQL/문서만 두고, 실제 학습/추론은
그쪽 코드로 실행). addi 전용 데이터/모델은 abi 것과 섞이지 않도록 별도 경로 사용:

```
# 1) Athena에서 01/02.sql(addi 버전) 실행 → CSV 다운로드 →
#    user-to-ad-encoder/data/ 아래 addi 전용 이름으로 저장
#    (예: data/addi_top500_media_visit.csv, data/addi_user_profile.csv)

# 2) 학습 (아티팩트를 abi와 분리된 디렉터리에 저장)
.venv\Scripts\python.exe -m train.user_profile   --input data/addi_user_profile.csv      --output data/models/user_profile_addi
.venv\Scripts\python.exe -m train.media_sequence --input data/addi_top500_media_visit.csv --output data/models/media_sequence_addi

# 3) 추론 (신규 캠페인 유저가 새로 들어올 때마다 반복 실행)
.venv\Scripts\python.exe -m inference.user_profile   --input <신규배치>.csv --model-dir data/models/user_profile_addi   --output data/embeddings/user_profile_addi_scored.csv
.venv\Scripts\python.exe -m inference.media_sequence --input <신규배치>.csv --model-dir data/models/media_sequence_addi --output data/embeddings/media_sequence_addi_scored.csv
```

`--input` 스키마는 01/02.sql 출력과 동일해야 하며(`inference/media_sequence.py`는 이벤트
그레인 여러 행 필요), 학습 시점에 없던 값(신규 미디어/기기 모델 등)은 전부 `<UNK>`로 인코딩된다.

## 4. 아직 구현 안 된 부분 — 이 프로젝트가 새로 채워야 할 것

`user-to-ad-encoder`에도 "두 임베딩 결합"과 "유사 오디언스 탐색" 자체는 미구현 상태다
(`README.md` §7, `evaluation/distance.py`는 N×N 전체 거리 행렬만 계산 — 신규 유저를 기존
리스트와 비교하는 용도가 아님). 이 프로젝트에서 새로 만들어야 하는 부분:

### 4-1. 임베딩 결합(fusion)
- 1차: `user_profile`(64) + `media_sequence`(64) **단순 concat → 128차원**. 두 모듈 다
  이미 64차원으로 맞춰둔 상태라(원본 설계 의도) 별도 학습 없이 바로 가능.
- 2차(필요시): concat이 변별력 부족하면 작은 fusion MLP(128→64)를 대조학습(contrastive)이나
  다운스트림 라벨(§4-3의 실제 전환 여부)로 미세 조정하는 것을 고려. 1차 결과를 보고 결정.

### 4-2. 유사도 기반 스코어링 (신규 스크립트 필요)
`evaluation/distance.py`는 N×N 행렬이라 전체 유저 규모에서는 못 씀(예: addi user_profile
distinct 유저가 수백만 단위 — N² 불가능). 대신:
- **Seed 집합**: 과거 캠페인의 `querys/audience_list_extraction/J2` 결과(관심 유저 리스트,
  `device_ifa` 그레인) → `device_ifa`↔`req_user_id` 매핑(H7, 거의 1:1 확인됨)으로 변환해
  seed의 fused 임베딩 집합을 구성.
- **스코어링 방식 후보**:
  - Seed 집합의 centroid(평균 벡터) 하나와의 코사인 유사도 — 가장 단순, 계산량 적음.
  - Seed 집합에 대한 k-NN 유사도(top-k 평균 거리) — centroid보다 다봉분포(multi-modal) 유저군에
    강건하지만 근사 최근접 탐색(예: FAISS) 필요할 수 있음(seed가 수천~수만이면 brute-force도 가능).
  - 권장: 우선 centroid 방식으로 베이스라인을 만들고, 정확도가 부족하면 k-NN으로 전환.
- **대상 집합**: 신규 캠페인의 bid_exposure 중 postback 없는(T1) 유저 — 기존
  `J1_audience_tier_full.sql`에서 이미 이 유저군을 뽑고 있음(`interest_tier = 'T1_노출만'`).
- **출력**: 신규 유저별 유사도 점수 → 임계값 또는 상위 K명 컷 → "관심 예상 신규 유저" 리스트.

### 4-3. 검증(비교적 장기 후속 작업)
지금 시점엔 "임베딩 유사도가 실제 전환을 예측하는지" 검증된 바 없음(가설 단계). 예측
리스트를 뽑은 뒤 일정 기간 기다렸다가 실제 postback 발생 여부로 backtest 필요:
- 예측 상위 K명의 실제 전환율 vs 무작위/전체 평균 전환율 비교 (lift 확인).
- lift가 유의미하지 않으면 §4-1의 fusion 방식이나 §2의 피처 구성(예: user_profile 필드
  추가/제외)을 재검토.

## 5. 남은 의사결정 / 확인 필요 사항
- **학습 기간 확장 여부**: →§7에서 2026-04~05(2개월)로 확정. media_sequence 신호 품질은 실제 학습 후 재평가.
- **Seed 집합 범위**: 유사도 스코어링의 seed를 특정 캠페인 하나(J2 예시: cmp_no=10115)로 할지, 여러 캠페인의 T3+ 이상 유저를 합쳐 "일반적 관심 유저" seed로 확장할지 — 캠페인 성격에 따라 갈릴 수 있어 실제 신규 캠페인이 정해지면 논의. §7의 파일럿은 우선 전체 캠페인 풀링으로 진행.
- **fusion 고도화(§4-1 2차) 착수 시점**: 1차 concat 결과의 정성 평가(코사인 거리 분포, 상위 유사 유저 샘플 확인) 이후 판단.

## 6. 실행 순서 요약
1. `querys/audience_embedding/01_top500_media_visit.sql`, `02_user_profile.sql` Athena 실행 → CSV 다운로드
2. `user-to-ad-encoder`에서 addi 전용 경로로 학습 (§3)
3. 두 임베딩 concat (§4-1 1차)
4. 과거 캠페인 J2 리스트로 seed centroid 계산 + 신규 T1 유저 스코어링 스크립트 작성 (§4-2, 아직 코드 없음 — 다음 단계로 진행 여부 확인 후 작성)
5. 결과 리스트 산출 → (시간 경과 후) §4-3 backtest

## 7. 단기 목표: 2026-04~05 학습 → 2026-06 신규 유저 스코어링

`CLAUDE.md`에 명시된 현재 단기 목표. §3~§4를 구체적인 달력 기간에 맞춰 실행 가능한 계획으로
좁힌 것 — **"4~5월 addi bid log + addi postback log로 임베딩 모델을 학습하고, 6월에 새로
등장한 유저를 그 임베딩 공간에서 과거 관심 유저와 얼마나 가까운지로 스코어링한다."**

### 7-1. 기간/집합 정의

| 구분 | 기간 | 용도 |
|---|---|---|
| 학습(training) | 2026-04-01 ~ 2026-05-31 | `user_profile`/`media_sequence` 임베딩 모델 학습 데이터 (addi_bid_log_flatten) |
| 시드(seed/reference) | 2026-04-01 ~ 2026-05-31 (학습과 동일 기간) | "과거 관심 유저" 기준 집합 — addi_bid_log_flatten **+ addi_postback_log**로 J1 방식(T2 이상) 티어링 |
| 스코어링 대상 | 2026-06-01 ~ 2026-06-30 | "6월 신규 유저" — 4~5월 bid log에 없다가 6월에 처음 등장한 유저만 (postback 유무 무관, 아직 반응 안 한 유저를 찾는 게 목적이므로 postback 없는 유저가 핵심 관심 대상) |

**"신규 유저"의 판정 기준**: 6월 bid log의 `req_user_id`(또는 `device_ifa`) 중 4~5월 bid log에
전혀 등장하지 않은 것만 — 6월 bid log를 4~5월 bid log와 `LEFT JOIN`해서 4~5월 쪽이
`NULL`인 유저.

**시드 집합에 postback이 필요한 이유**: 임베딩 자체(01/02.sql)는 bid log만 쓰지만(§1), "누가
과거에 관심을 보였는가"를 정의하려면 `J1_audience_tier_full.sql`처럼 postback 기반 티어링이
필요하다 — 그래서 이 단기 목표에서만 postback log가 추가로 등장한다.

### 7-2. 체크리스트 (완료 / 신규 필요)

| # | 작업 | 상태 |
|---|---|---|
| 1 | `01_top500_media_visit.sql`/`02_user_profile.sql` 기간을 `2026-04-01~2026-05-31`로 변경 | **완료** |
| 2 | 4~5월 시드(관심 유저) 집합 쿼리 — `03_seed_interested_users_apr_may.sql` (J2 기반, cmp_no 필터 없이 전체 캠페인 풀링, T2 이상만 출력, req_user_id 그레인) | **완료** |
| 3 | 6월 신규 유저 추출 쿼리 — `04_new_users_top500_media_visit_jun.sql`(media_sequence 입력), `05_new_users_user_profile_jun.sql`(user_profile 입력). 둘 다 04-05월 bid log에 없던 `req_user_id`만 anti-join으로 필터. 04는 학습 시 top500 재필터링을 하지 않음(vocab 어긋남 방지) | **완료** |
| 4 | `user-to-ad-encoder`에서 학습: `--input`을 4~5월 CSV(01/02 결과)로, `--output`을 `data/models/*_addi`로 (§3 그대로) | 기존 코드 재사용, Athena 실행 → CSV 확보 후 바로 가능 |
| 5 | `user-to-ad-encoder`에서 추론: 6월 신규 유저 CSV(04/05 결과) → 임베딩 추출 (§3 그대로) | 기존 코드 재사용 |
| 6 | fusion(concat, §4-1) + 시드(03 결과) centroid 코사인 거리 스코어링 스크립트 | **신규 작성 필요** — 아직 어느 저장소에도 없음 |
| 7 | 결과(6월 신규 유저별 유사도 점수) 산출 | 6번 완료 후 |
| 8 | (후속) 시간이 지나 6월 유저의 실제 postback이 쌓이면 lift backtest (§4-3) | 향후 |

### 7-2-1. 샘플링 (2026-07-07 추가)

01/02/04/05 전부 캠페인 무필터라 실제 데이터량이 너무 커서(7일 8,990만 건 기준 2개월
환산 시 7~8억 건대, Athena 콘솔에서 CSV로 받기 비현실적) 유저 단위 5% 샘플링을 추가했다:

```sql
mod(crc32(to_utf8(CAST(req_user_id AS VARCHAR))), 100) < 5
```

`req_user_id` 해시 기준이라 같은 유저는 항상 같은 결과(포함/제외)를 받는다(결정적) — 기간을
줄이는 대신 유저 수만 줄이므로, 뽑힌 유저의 시퀀스 길이(2개월치)는 그대로 보존된다. **01과
02는 반드시 동일 조건**(같은 유저 집합), **04와 05도 반드시 동일 조건**을 써야 한다.
04/05(6월 스코어링 대상)도 지금은 파일럿이라 같이 5%로 축소했다 — 실제 후보 리스트를 산출할
단계에서는 04/05의 샘플링 조건만 제거하고 전체 신규 유저로 재실행해야 한다(01/02 학습 데이터
샘플링은 유지해도 무방, 모델은 이미 학습된 상태로 재사용).

### 7-3. 아직 열려있는 것
- 03(시드) 쿼리는 전체 캠페인 풀링으로 작성함 — 특정 캠페인으로 좁힐 실제 니즈가 생기면 J2처럼 `cmp_no` 필터를 추가.
- 4~5번(Athena 실행 → CSV 다운로드 → 학습/추론 실행)은 사용자가 Athena에서 01~05.sql을 돌려야 진행 가능.
- 6번(fusion + 스코어링 스크립트)은 아직 코드가 없음 — 4~5번으로 임베딩 CSV가 확보되면 다음 단계로 작성.

### 7-4. 첫 학습 실행 결과 + `media` 아이템 재정의 (2026-07-07)

01~05.sql을 Athena에서 실행해 `sample_data/audience_embedding/`에 CSV 확보 후 실제 학습을
시도한 기록. 두 가지 문제를 겪고 대응했다.

**문제 1: 데이터량/속도** — 01(2개월치, 캠페인 무필터) 결과가 2,197만 행(3.75GB)이라 `user_profile`
(단순 오토인코더, 30 epoch)은 26분 만에 끝났지만 `media_sequence`(SASRec, 30 epoch 기본값)는
1시간 40분 넘게 걸려도 안 끝남 — CPU 전용 환경에서 Transformer를 59만 유저 규모로 학습하는
게 근본적으로 무거운 것이 원인(py-spy로 프로세스 스택을 찍어 실제 forward pass 중임을 확인,
멈춘 게 아니었음). 대응:
- **로컬 다운샘플링**: Athena 재실행 없이, 이미 받은 CSV를 로컬에서 유저 10만 명으로 추가로
  줄임(`req_user_id` 단위, pandas `sample()`). Athena에서의 5% 샘플링과 별개로 로컬에서 한 번
  더 줄인 것 — 반복 실험 속도를 위한 것이고, 최종 프로덕션 실행 시엔 필요 없다.
- **epoch 30 → 5**로 축소 (파일럿 목적, `config/addi_media_sequence.json`).
- **로그 스팸 수정**: `train/user_profile.py`, `train/media_sequence.py`의 tqdm 호출에
  `mininterval=5.0` 추가 — 콘솔이 아닌 파일로 리다이렉트할 때 반복 갱신이 그대로 쌓여 로그가
  과도하게 커지는 문제 완화.
- 위 조정 후 5 epoch/10만 유저 학습이 약 6~7분으로 단축됨.

**문제 2 (더 중요함): `media`(시퀀스 아이템) 자체가 거의 상수였음** — `media`를 원본 abi
설계대로 `app_bundle`로 채웠더니, addi CTV 인벤토리에서는 app_bundle이 통신사 IPTV 앱
3종(`com.skb.adui`/`com.kt.google.ad.viewer`/`com.lguplus.iptv.base.livetvinput`)뿐이라
`vocab size=5`(3개 값 + `<NA>` + `<UNK>`)로 사실상 상수. 다음-아이템 예측이 아무 의미가 없어져
epoch 1부터 loss가 `0.0000`으로 수렴(=아무것도 안 배움). **`content_genre`의 대표(콤마로 구분된
문자열의 첫) 토큰으로 `media`를 바꿔서 재정의**했다 — vocab size가 115로 늘고, loss가
`3.70 → 2.56 → 2.45 → 2.40 → 2.37`로 정상적으로 감소(5 epoch 기준, 계속 완만히 하락 중이라
epoch을 늘리면 더 내려갈 여지 있음). `01_top500_media_visit.sql`/
`04_new_users_top500_media_visit_jun.sql`에 반영 완료 — `media` 컬럼명은 embedding 코드와의
계약을 위해 그대로 두되, 실제 값은 app_bundle이 아니라 콘텐츠 장르 대표값이다.
`content_genre` 컬럼(보조 피처, 전체 다중 장르)은 그대로 유지 — media(대표 장르 1개)와 일부
겹치지만 코드 수정 없이 재사용 가능하다는 이점이 더 크다고 판단.

**현재 아티팩트** (모두 `user-to-ad-encoder/data/models/`, 프로덕션 재학습 전 파일럿용):
| 모듈 | 학습 데이터 | epoch | 상태 |
|---|---|---|---|
| `user_profile_addi` | 4~5월 59만 유저 (Athena 5% 샘플) | 30 | 완료 |
| `media_sequence_addi_genre` | 4~5월 10만 유저 (로컬 추가 샘플), `media`=content_genre 대표값 | 5 | 완료 |

다음 프로덕션 학습 시엔 (a) `media_sequence`도 59만 유저 전체로, (b) epoch을 30(또는 loss
추이를 보며 조정)으로 되돌리는 것을 고려 — 지금은 파이프라인이 끝까지 도는지 확인하는
파일럿이라 축소된 채로 두었다.
