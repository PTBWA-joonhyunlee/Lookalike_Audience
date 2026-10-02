# 분류기 클래스 불균형 처리 방식 비교 (je seed, 2026-10-02)

## 배경

je seed(1,188명, 세그먼트 보유자)로 첫 실행(`run_seed_scenario1`)을 했더니 검증 AUC가 epoch 1(0.705)
이후 내려갔다(20 epoch 후 0.6665). train loss는 계속 감소 → 과적합. 원인 후보는 두 가지였다.

1. 기존 학습이 `WeightedRandomSampler`(복원추출)로 양성을 에폭마다 pool 규모(약 204만 건)만큼
   뽑는다 → 양성 약 950명을 에폭당 수백 번 반복해서 보게 돼 seed를 외움.
2. 저장되는 모델이 검증 최고 에폭이 아니라 마지막 에폭이었다.

## 실험 설정

- 데이터: seed 1,188 / pool 2,548,960(`legacy` pool, 2026-04~05) / 임베딩 32차원(기존 Autoencoder).
- 분할: 양성/음성을 따로 섞는 층화 80/10/10(train/val/test). test 양성 118명. 분할 seed 3회(0,1,2).
- 에폭 선택은 val AUC, **비교 지표는 에폭 선택에 쓰지 않은 test AUC**(val 최고값은 낙관적이다).
- 코드: `lookalike/scoring/compare_imbalance.py`, 학습 `lookalike/scoring/train_lookalike.fit`.
  결과 원본: `data/seeds/je/20261002/imbalance_comparison.json`.

| 방식 | 설명 |
|---|---|
| baseline | 복원추출 + 20 epoch 고정 + 마지막 에폭 모델(기존 동작) |
| sampler + early stop | 같은 복원추출, patience 5 + val 최고 에폭 모델 |
| posweight + early stop | pool 셔플로 한 번씩, BCE `pos_weight = n_neg/n_pos`(양성 반복 없음) |
| undersample(20:1) + early stop | 에폭마다 양성 전부 + 음성 20배 비복원 추출, `pos_weight=20` |

## 결과 (test AUC, 3회)

| 방식 | rep0 | rep1 | rep2 | 평균 ± 표준편차 | best epoch 평균 | 시간/회 |
|---|---|---|---|---|---|---|
| baseline | 0.6798 | 0.7106 | 0.7255 | 0.7053 ± 0.0190 | 3.3 | ~95s |
| sampler + early stop | 0.7275 | 0.7137 | 0.7564 | 0.7325 ± 0.0178 | 3.3 | ~40s |
| **posweight + early stop** | 0.7440 | 0.7518 | 0.7646 | **0.7535 ± 0.0085** | 5.7 | ~47s |
| undersample(20:1) + early stop | 0.7095 | 0.7425 | 0.7600 | 0.7373 ± 0.0210 | 13.3 | **~3s** |

## 해석

- **early stopping(1번)**: baseline 대비 3회 모두 개선(평균 +0.027). 최고 에폭이 1~5로 빨라서 마지막 에폭
  모델이 일관되게 손해였다.
- **posweight(2번)**: 같은 early stop 조건의 sampler보다 3회 모두 높고(+0.021 평균) 분산도 가장 작다.
  복원추출의 양성 반복 노출이 문제였다는 가설과 방향이 맞다.
- **undersample**: posweight와 비슷한 수준이지만 분산이 크고 best epoch이 늦다(양성 대 음성 비율/에폭 수를
  더 만져봐야 함). 속도는 15배 이상 빠르다.
- **한계**: test 양성이 118명이라 AUC 한 번의 오차가 ±0.02 수준이고, 분할 3회는 적다. posweight와
  undersample의 차이(0.016)는 이 노이즈 안에 있다 — 결론은 "복원추출은 안 쓰는 게 낫다" 정도까지만
  말할 수 있다. 어느 방식이든 절대 성능은 0.75 안팎이라 je seed 신호 자체는 약하다(seed 1,188명, 32차원
  segment 임베딩 한계 가능성 — 이번 실험에서 검증하지 않음).

## 조치

`train_lookalike.train()` 기본값을 `imbalance="posweight"`, `patience=5`, 저장 모델은 val 최고 에폭으로
변경. `sampler`/`undersample`은 옵션으로 남김.
