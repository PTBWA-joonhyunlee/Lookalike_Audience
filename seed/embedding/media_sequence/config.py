# seed/embedding/media_sequence/config.py
#
# 입력 스키마는 seed/queries/lib/02_user_media.sql(및 seed/queries/04b/05b/07b_*_media.sql)의
# 출력과 맞춘다. 옛 addi 트랙 embedding/media_sequence/config.py를 propfit 스키마로 이식 —
# content_genre 컬럼이 없는 대신 inventory_type(app/site)이 있어 이걸 ad_type/connection_type과
# 같은 단일값 보조 피처로 다룬다(dataset.py/model.py 헤더 참고).

from pathlib import Path

# seed/embedding/media_sequence/config.py -> parent 4번 = 저장소 루트(seed/의 상위).
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 04b_seed_media.csv / 05b_pool_media.csv / 07b_candidate_media.csv (이벤트 그레인, 합쳐서
# 최대 14GB) — build_features.py가 청크 단위로 스트리밍 처리한다(전체를 한 번에 메모리에
# 올리지 않음).
DATA_DIR = PROJECT_ROOT / "data" / "seed"
DATA_GLOB = "*_media.csv"

ARTIFACT_DIR = PROJECT_ROOT / "data" / "models" / "media_sequence"
FEATURES_NPZ_PATH = ARTIFACT_DIR / "media_features.npz"
MEDIA_VOCAB_PATH = ARTIFACT_DIR / "vocab_media.json"
INVENTORY_TYPE_VOCAB_PATH = ARTIFACT_DIR / "vocab_inventory_type.json"
AD_TYPE_VOCAB_PATH = ARTIFACT_DIR / "vocab_ad_type.json"
CONNECTION_TYPE_VOCAB_PATH = ARTIFACT_DIR / "vocab_connection_type.json"
MODEL_PATH = ARTIFACT_DIR / "model.pt"

ID_COL = "device_ifa"
MEDIA_COL = "media"
TS_COL = "ts"
INVENTORY_TYPE_COL = "inventory_type"
AD_TYPE_COL = "ad_type"
CONNECTION_TYPE_COL = "connection_type"

# 03_create_media_vocab_table.sql이 이미 전체 모집단 기준 top500으로 media를 제한해뒀으므로
# 카디널리티가 낮다. min_freq=1(전부 포함), max_size는 방어적 상한만 둔다.
MIN_FREQ = 1
MAX_VOCAB_SIZE = 500

SIDE_FEATURE_MIN_FREQ = 1
INVENTORY_TYPE_MAX_VOCAB_SIZE = 10   # app/site 2종 + <NA>/<UNK>
AD_TYPE_MAX_VOCAB_SIZE = 20
CONNECTION_TYPE_MAX_VOCAB_SIZE = 20

MAX_SEQ_LEN = 50     # 유저당 최근 N스텝만 사용(그보다 길면 앞부분을 자름)
MIN_SEQ_LEN = 5      # 이벤트가 이보다 적은 유저는 학습/추론 임베딩에서 제외
                      # (다음-아이템 예측 신호가 너무 약해 신뢰하기 어려움)

EMBED_DIM = 64
N_HEADS = 2
N_LAYERS = 2
FFN_DIM = 128
DROPOUT = 0.2

BATCH_SIZE = 128
NUM_EPOCHS = 30
LEARNING_RATE = 1e-3

# build_features.py가 CSV를 스트리밍 읽을 때 한 번에 처리하는 행 수.
CHUNK_SIZE = 2_000_000
