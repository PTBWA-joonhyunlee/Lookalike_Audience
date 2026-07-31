# seed/ — 피엘라벤 seed 기반 신규 유저 룩어라이크

외부에서 확보한 브랜드 seed 리스트(현재: 피엘라벤)를 두고, propfit 소스에서 비슷한
신규 유저를 찾는 트랙. 자세한 실행 순서·산출물·설계 결정은 [`docs/README.md`](docs/README.md),
모델 구조는 [`docs/model_architecture.md`](docs/model_architecture.md) 참고. 조사 과정
(ID 공간 크로스워크, 표본 버그 등)은 저장소 루트의 [`../eda/`](../eda/) 참고.

이 폴더는 **독립 작업 루트**다 — 저장소 루트가 아니라 여기로 `cd` 한 뒤 실행한다
(패키지 최상위가 여기 `seed/`이므로).

```
cd seed
..\.venv\Scripts\python.exe -m embedding.segment_features.build_features
..\.venv\Scripts\python.exe -m train.segment_features
..\.venv\Scripts\python.exe -m inference.segment_features
..\.venv\Scripts\python.exe -m scoring.train_lookalike
..\.venv\Scripts\python.exe -m scoring.infer_lookalike --top-pct 10
```

## 폴더 구조

```
queries/
  lib/            propfit 피처 추출 라이브러리(01_user_profile/02_user_media/11_user_embedding_features)
  01~07*.sql       seed 파이프라인(seed 테이블 등록 → 크로스워크 → 피처 추출 → pool/후보)
embedding/
  common/          공용 유틸(vocab/device/train_config/config_file)
  segment_features/  skp 세그먼트 임베딩(Autoencoder) 모델 정의
train/
  segment_features.py   위 모델 학습 스크립트
inference/
  segment_features.py   학습된 모델로 임베딩(z) 추출 스크립트
scoring/
  config.py/model.py/dataset.py   지도학습 lookalike 분류기 정의
  train_lookalike.py    seed=1/pool=0으로 분류기 학습
  infer_lookalike.py    candidate 스코어링 + 상위 후보 추출
config/
  train_config.example.json
docs/
  README.md              실행 순서 + 현재 산출물 + 설계 결정
  model_architecture.md  모델 구조 스펙 + 스코어링 파이프라인
```
