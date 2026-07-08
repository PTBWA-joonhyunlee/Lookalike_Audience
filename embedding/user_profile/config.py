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
# carrier/device_make/device_model은 카디널리티가 높아 cutoff를 더 빡빡하게 잡는다.
CATEGORICAL_FIELDS = {
    "device_os":         {"min_freq": 1,  "max_size": None, "embed_dim": 8,  "preprocess": identity},
    "device_os_version": {"min_freq": 1,  "max_size": 100,  "embed_dim": 8,  "preprocess": major_version},
    "device_type":       {"min_freq": 1,  "max_size": None, "embed_dim": 8,  "preprocess": identity},
    "device_lmt":        {"min_freq": 1,  "max_size": None, "embed_dim": 4,  "preprocess": identity},
    "country":           {"min_freq": 1,  "max_size": 300,  "embed_dim": 8,  "preprocess": identity},
    "language":          {"min_freq": 1,  "max_size": 200,  "embed_dim": 8,  "preprocess": identity},
    "region":            {"min_freq": 5,  "max_size": 2000, "embed_dim": 16, "preprocess": identity},
    "carrier":           {"min_freq": 20, "max_size": 5000, "embed_dim": 16, "preprocess": identity},
    "device_make":       {"min_freq": 20, "max_size": 2000, "embed_dim": 16, "preprocess": identity},
    "device_model":      {"min_freq": 10, "max_size": 5000, "embed_dim": 24, "preprocess": identity},
}

# 수치형 필드: log1p 적용 여부 (표준화는 항상 적용). device_lmt는 사실상 플래그라
# 위 CATEGORICAL_FIELDS 쪽에 넣었다.
NUMERIC_FIELDS = {
    "device_w":       {"log1p": True},
    "device_h":       {"log1p": True},
    "device_pxratio": {"log1p": False},
}

HIDDEN_DIM = 128
EMBED_DIM = 64

BATCH_SIZE = 256
NUM_EPOCHS = 30
LEARNING_RATE = 1e-3
