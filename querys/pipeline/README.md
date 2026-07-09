# querys/pipeline/

이 저장소의 유일한 활성 파이프라인 — "postback 유저 중 실제 몰(`raw_conv_web`/`raw_conv_web_imp`)
IP 매칭 여부"를 전환으로 보고, 그 전환 가능성을 임베딩 기반 스코어링으로 예측/검증하는
10단계 쿼리. 전체 실행 순서/커맨드는 루트 [`README.md`](../../README.md) 참고.

| # | SQL | 역할 | 대응 pipeline 단계 |
|---|---|---|---|
| 01 | `01_pool_profile_apr_may.sql` | pool 프로필(4~5월 5% 샘플) | 1. 데이터 수집 |
| 02 | `02_pool_media_apr_may.sql` | pool 미디어 방문(4~5월 5% 샘플) | 1. 데이터 수집 |
| 03 | `03_seed_users_apr_may.sql` | 시드(양성) 유저 목록 — IP+cmp_no 매칭 | 4. 학습 신호 수집 |
| 04 | `04_seed_profile_apr_may.sql` | 시드 유저 프로필(전수) | 4. 학습 신호 수집 |
| 05 | `05_seed_media_apr_may.sql` | 시드 유저 미디어 방문(전수) | 4. 학습 신호 수집 |
| 06 | `06_backtest_labels_jun.sql` | 6월 backtest 라벨 — IP 매칭 여부 | 4. backtest용 데이터셋 |
| 07 | `07_scoring_target_profile_jun.sql` | 6월 postback 유저 전체 프로필 | 5. score 모델 학습(스코어링 대상, 백테스트/검증용) |
| 08 | `08_scoring_target_media_jun.sql` | 6월 postback 유저 전체 미디어 방문 | 5. score 모델 학습(스코어링 대상, 백테스트/검증용) |
| 09 | `09_new_users_profile_jun.sql` | 6월 신규 유저(4~5월에 없던 유저) 프로필 | 6. 실제 후보 리스트 산출 |
| 10 | `10_new_users_media_jun.sql` | 6월 신규 유저 미디어 방문 | 6. 실제 후보 리스트 산출 |

01/02(pool)와 03~05(시드)는 `scoring.build_stratified_pool`로 병합돼 분류기 학습 입력이 되고,
07/08로 스코어링한 결과를 06의 라벨과 대조해 백테스트한다(§2 참고). **07/08(postback 유저
전체)은 4~5월 pool/시드와 겹칠 수 있어 학습-검증 leakage 위험이 있다** — 백테스트는
"모델이 그럴듯한지" 확인하는 용도로만 쓰고, 실제 후보 리스트는 4~5월에 아예 없던 09/10
(신규 유저, 정의상 pool/시드와 안 겹침)로 뽑는다.

## 배경 — 왜 이렇게 됐는지

"postback tier(T2+) 도달 여부"를 전환으로 보던 이전 트랙(신규 유저 룩어라이크 타겟팅용)은
삭제했다 — 실제 몰 전환(IP 매칭)이라는 더 신뢰할 수 있는 정의를 쓰기로 결정했기 때문
(2026-07-09). `raw_conv_web(_imp)` 스키마 조사, 매칭 신뢰도 진단, 5% 샘플링/극단적 클래스
불균형 대응 등 결정 과정과 수치는 아래 실험 기록에 남아있다:

- [`docs/_archive/202607091533.md`](../../docs/_archive/202607091533.md) — 스키마 진단,
  절대 매칭 건수, 1차 백테스트(재학습 전)
- [`docs/_archive/202607091610.md`](../../docs/_archive/202607091610.md) — 재학습(층화 pool,
  불균형 대응) 및 결과
