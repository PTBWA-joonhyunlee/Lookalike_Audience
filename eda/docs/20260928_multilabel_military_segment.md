# 2026-09-28 군 관련 seed 4종 멀티라벨(멀티헤드) 분류기 — 1차 실험

## 설정

- seed(전부 raw GAID, id space direct — `eda/queries/id_space_check/16~19_*`):
  전역남성 `discharged_male` 199,498 / 부모 `parents` 253,548 / 곰신 `gomsin` 144,081 /
  입대예정 `enlistee` 130,881 (skp 세그먼트 보유 기준). 2개 이상 라벨 동시 보유 128,091명.
- pool: 기존 피엘라벤 pool(`pool_segment.csv`) 재사용 → pool에만 있는 유저 2,538,379명.
- candidate: 2026-06-01~09-25 bid log, KR/Android, 컴플라이언스, 전 seed 제외
  (`seed/queries/segment/04_candidate_segment_parents.sql`, 4종 공용) → 5,138,371명.
- 입력: segment Autoencoder 임베딩 32dim(재학습 없이 forward). 모델: 공유 trunk(64-64) +
  라벨별 sigmoid 헤드 4개, 헤드별 pos_weight BCE, 20 epoch, best epoch=19.
- 실행: `pipeline.run_multilabel_pipeline --variant military --top-pct 10`.
  산출물 `data/models/lookalike_multilabel_military/`.

## 누수 점검(학습 전)

군 관련 세그먼트 보유율(seed / pool 30만 표본): 군교육기관 6~8% / 1.2%, 직업별_군인
0.6~0.7% / 0.1%, 유아동·초등생 부모 추정 10~22% / 1%, 군인&연인·군대일기 0% / 0%.
→ seed를 정의하는 세그먼트는 없음(최대 8%). 농축 신호 수준이라 제외하지 않고 학습.

## 결과

| 라벨 | val AUC vs pool | val AUC vs rest | seed끼리만 AUC(raw) | seed끼리만 AUC(relative) |
|---|---|---|---|---|
| discharged_male | 0.956 | 0.905 | 0.563 | 0.591 |
| parents | 0.956 | 0.912 | 0.562 | 0.578 |
| gomsin | 0.953 | 0.894 | 0.538 | 0.566 |
| enlistee | 0.947 | 0.884 | 0.517 | 0.557 |

- "seed끼리만"은 seed 유저(라벨 1개 이상)만 두고 그 라벨 vs 다른 seed를 구분한 AUC(학습
  데이터 포함이라 낙관적). relative = 그 헤드 logit − 나머지 헤드 logit 평균.
- candidate 점수의 라벨 간 Spearman 상관 0.994~0.997.
- 라벨별 상위 10%(각 513,812명)의 합집합 573,214명 중 **470,813명(82%)이 4개 라벨 전부**에
  선택됨. 라벨 쌍별 상위 10% 겹침 93~97%.

## 해석

- "군 관련 seed vs 일반 모집단"은 segment 임베딩으로 잘 구분된다(AUC ~0.95).
- 하지만 **seed 4종끼리는 segment 피처로 거의 구분이 안 된다**(AUC 0.52~0.59) — 헤드 4개가
  사실상 같은 방향("군 관련 여부")을 학습했고, 라벨별 추출 리스트도 거의 같은 사람들이다.
- 원인은 모델 구조보다 데이터 쪽으로 보인다: 원본 skp 인구통계조차 seed 간 차이가 거의
  없다(성별 점수 분포 비슷, 연령대 결측 68~81%, 입대예정 seed에 20대 태그 ~1%). seed 라벨의
  구분 기준(외부 출처)이 skp가 보는 정보와 다른 축에 있다고 추정.
- 이 상태에서 라벨별 리스트를 "서로 다른 오디언스"로 쓰면 안 된다. 실사용은 (a) 합집합을
  "군 관련 관심" 단일 오디언스로 쓰거나, (b) 라벨 구분이 필요하면 bid log 기반 피처(방문
  앱/사이트, 시간대 등) 추가가 필요.
