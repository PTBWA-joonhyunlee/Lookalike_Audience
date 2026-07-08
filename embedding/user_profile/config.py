# embedding/user_profile/config.py
#
# 입력 스키마는 querys/audience-embedding-similarity/02_user_profile.sql의 출력과 맞춘다.
# req_user_id / device_ifa / update_dt는 CATEGORICAL_FIELDS·NUMERIC_FIELDS 어디에도
# 없으므로 학습 피처에서 자동으로 빠진다 (화이트리스트 방식 — 과거 파이프라인에서 겪었던
# "의도치 않은 컬럼이 피처로 새어 들어가는 사고" 재발 방지와 동일한 이유).

from pathlib import Path

from .preprocessing import identity, major_version

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 02_user_profile.sql 결과 CSV 위치 (data/user_profile*.csv)
DATA_DIR = PROJECT_ROOT / "data"
DATA_GLOB = "user_profile*.csv"

ARTIFACT_DIR = PROJECT_ROOT / "data" / "models" / "user_profile"   # model.pt / vocab_*.json / numeric_scalers.json
EMBEDDINGS_DIR = PROJECT_ROOT / "data" / "embeddings"

ID_COL = "req_user_id"

# 범주형 필드: min_freq 미만이거나 max_size를 넘는 저빈도 값은 <UNK>로 묶인다.
# 컬럼 축소(2026-07-08): device_os/device_type/device_lmt/country/language/carrier/
# device_make/device_model은 addi CTV 인벤토리 실측 결과 전부 상수이거나 거의 전부 NULL이라
# (예: device_make=100% "Android", carrier=99.99% NULL) 학습 피처에서 뺐다. carrier 대신
# app_bundle(통신사 IPTV 앱, SKB/KT/LGU+ 3종 — 늘 채워져 있고 유저별로 기간 내내 고정값)을
# 넣었다. 자세한 사유는 02_user_profile.sql 주석 및 docs/model_architecture.md 참고.
CATEGORICAL_FIELDS = {
    "device_os_version": {"min_freq": 1, "max_size": 100,  "embed_dim": 8,  "preprocess": major_version},
    "region":            {"min_freq": 5, "max_size": 2000, "embed_dim": 16, "preprocess": identity},
    "app_bundle":        {"min_freq": 1, "max_size": 10,   "embed_dim": 4,  "preprocess": identity},
}

# 수치형 필드: device_w/device_h(상수)와 device_pxratio(전부 NULL)를 빼서 현재 없음
# (UserProfileAutoencoder/UserProfileDataset은 NUMERIC_FIELDS가 비어 있어도 그대로 동작한다).
NUMERIC_FIELDS = {}

HIDDEN_DIM = 128
EMBED_DIM = 64

BATCH_SIZE = 256
NUM_EPOCHS = 30
LEARNING_RATE = 1e-3
