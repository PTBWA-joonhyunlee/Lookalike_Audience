# 모델 아키텍처 스펙

`embedding/`(모델 정의) 기준 요약. 필드/하이퍼파라미터를 바꾸면 이 문서도 같이 갱신한다.
실행 방법은 [`README.md`](../README.md) 참고, 이 문서는 "무엇을 어떻게 인코딩하는가"만 다룬다.

## 1. `user_profile` — Autoencoder (`embedding/user_profile/`)

입력: `data/raw/01_pool_profile_apr_may.csv`(유저 1행 스냅샷). 레이블 없이 "자기 자신을 복원"하는
reconstruction loss로 학습. 인코더 출력(64차원)이 임베딩, 디코더는 학습에만 쓰고 버림.

```
[범주형] → 필드별 nn.Embedding ─┐
                                  ├─ concat → Linear(128) → ReLU → Linear(64) = z (임베딩)
[수치형] → log1p(선택)+표준화 ─┘
z → Linear(128) → ReLU → 필드별 Linear(복원) → cross-entropy(범주형) / masked MSE(수치형)
```

| 필드 | 종류 | 임베딩 차원 | 비고 |
|---|---|---|---|
| `device_os_version` | 범주형 | 8 | 메이저 버전만 사용("14.2.1"→"14") |
| `region` | 범주형 | 16 | ISO-3166-2, min_freq=5 |
| `app_bundle` | 범주형 | 4 | 통신사 IPTV 앱 3종(SKB/KT/LGU+). 유저별로 기간 내내 고정값(멀티 유저 0명 확인) |

미사용(화이트리스트에 없음): `req_user_id`, `device_ifa`, `update_dt`.
하이퍼파라미터: hidden=128, embed_dim=64, batch=256, epoch=30, lr=1e-3(Adam).

**컬럼 축소(2026-07-08)**: 원래 `device_os`/`device_type`/`device_lmt`/`country`/`language`/
`carrier`/`device_make`/`device_model`/`device_w`/`device_h`/`device_pxratio`까지 11개
필드를 더 실었는데, addi CTV 인벤토리 실측 결과 전부 상수이거나 거의 전부 NULL이었다
(`device_os`=100% "android", `device_type`=100% "3", `device_make`=100% "Android",
`device_model`=100% "generic", `carrier`=99.99% NULL, `device_lmt`=100% NULL,
`device_pxratio`=100% NULL, `device_w`/`device_h`=상수 1920/1080, `country`=100% "KOR",
`language`=99.998% "ko"). 학습 피처로서 정보량이 없어 전부 빼고, `carrier`가 늘 NULL이라
못 쓰는 통신사 식별 신호를 `app_bundle`로 대체했다. `NUMERIC_FIELDS`는 현재 빈 딕셔너리.

## 2. `media_sequence` — SASRec (`embedding/media_sequence/`)

입력: `data/raw/02_pool_media_apr_may.csv`(이벤트 그레인: 유저×미디어×시각, 같은 유저가
같은 값을 30분 이내 재방문한 이벤트는 SQL에서 이미 제거됨). "다음에 뭘 볼지" 예측하는
causal next-item 학습(레이블 불필요). 마지막 실제 위치의 hidden state = 유저 임베딩(64차원).

**`media` = `content_genre`의 대표(콤마로 구분된 첫) 토큰이지 `app_bundle`이 아니다.**
addi는 CTV 인벤토리라 app_bundle이 통신사 IPTV 앱 3종뿐이라 vocab이 사실상 상수 —
다음-아이템 예측이 무의미해져서(loss가 처음부터 0에서 안 움직임) genre 기반으로 바꿨다.
바뀐 뒤 vocab 115종, loss가 정상적으로 감소함(3.70→2.37, 5 epoch 기준).

```
media(장르 대표값), content_genre(전체 장르, 보조), ad_type(보조), connection_type(보조, addi는 컬럼 없어 항상 NULL)
  → item_embedding + genre_embedding(EmbeddingBag, mean) + ad_type_embedding + connection_type_embedding + position_embedding (전부 합산)
  → TransformerEncoder(causal mask, 2 layer, 2 head)
  → 마지막 실제 위치 hidden state = 임베딩(64차원)
```

| 하이퍼파라미터 | 값 |
|---|---|
| `MAX_SEQ_LEN` | 50 (유저당 최근 50 스텝) |
| `EMBED_DIM` | 64 |
| `N_HEADS` / `N_LAYERS` / `FFN_DIM` | 2 / 2 / 128 |
| `MAX_VOCAB_SIZE`(media) | 500 (addi는 실제 115종만 사용) |
| `BATCH_SIZE` / `NUM_EPOCHS` / `LR` | 128 / 30(기본, 파일럿은 5) / 1e-3 |

시퀀스 길이 2 미만인 유저는 학습에서 제외되지만(다음 아이템을 만들 수 없어서), 추론
(`inference/media_sequence.py`)에서는 전부 포함해서 임베딩을 뽑는다.

## 3. Fusion + 스코어링 (`scoring/`, 지도학습 fusion 분류기)

두 임베딩(각 64차원)을 `req_user_id`로 concat → 128차원(`scoring/fused_embeddings.py`). 그
위에 얕은 MLP를 얹어 "시드(postback 유저 중 실제 몰 IP 매칭 전환)=1 / 비시드=0" 라벨로 직접
지도학습한다. 분류기 학습(`scoring/train_supervised_lookalike.py`)과 저장된 분류기로
스코어링 대상을 채점하는 스크립트(`scoring/infer_supervised_lookalike.py`)가 분리돼 있다 —
`scoring/fusion_classifier.py`(모델 정의 + 아티팩트 저장/로드)를 공유한다. 실행 커맨드는
[`README.md`](../README.md) §2-4 참고.

```
Linear(128→64) → ReLU → Dropout(0.2) → Linear(64→1) → sigmoid = 스코어
```

`BCEWithLogitsLoss`(클래스 불균형 보정 `pos_weight`), Adam lr=1e-3, batch=512, 20 epoch.
임베딩 자체는 재학습하지 않고 고정, 이 얕은 분류기만 학습. 시드(양성) 비율이 극단적으로
낮아서(0.01~0.17% 수준) 층화 미니배치 샘플링(`--pos-frac`)·라벨 층화 train/val 분할·PR-AUC
및 recall@top-K% 리포트를 추가했다 — 자세한 배경은
[`docs/_archive/202607091610.md`](_archive/202607091610.md) 참고.

**성능(2026-07-09 재학습, 6월 postback 유저 269,914명 백테스트)**: 층화 pool(음성 5% 샘플 +
양성 전수 388명, 총 425,043명) 기준 val_auc **0.79~0.82**, held-out(6월 IP 매칭 전환 라벨)
최상위 10% 누적 lift **1.60x**(decile 순서도 대체로 단조적). 자세한 수치/해석은
[`docs/_archive/202607091610.md`](_archive/202607091610.md) 참고. (시드 centroid 코사인
유사도 baseline은 최하위 10%만 구분하고 나머지는 순위를 못 매겨 폐기 — 히스토리는
`docs/_archive/` 참고.)

## 4. 아직 없는 것 / 다음 시도 후보

- `media_sequence`를 파일럿 축소(10만 유저/5epoch)가 아니라 전체 규모(59만+/30epoch)로 재학습
- 조기 종료/베스트 에폭 체크포인트 저장 — `val_recall@top10%`가 epoch마다 크게 흔들려서
  마지막 epoch가 최선이라는 보장이 없음(검증셋 양성이 수십 명 수준)
- centroid 대신/추가로 k-NN 스코어링
- `media_sequence` 단독 스코어링으로 `user_profile`이 신호를 얼마나 흐리는지 분리 검증
- 광고주(`addi_business`) 정보를 활용한 two-tower — **현재 데이터로는 불가능**(README 알려진
  이슈 참고, `cmp_no`↔`adspid` 매핑 없음)
