# seed/scoring/config.py
#
# segment 임베딩(embedding/segment_features)만 입력으로 쓰는 지도학습 lookalike 분류기.
# seed=1 / pool=0 라벨로 학습하고, candidate(2026-06)에 스코어링한다. profile/media
# 임베딩 모델이 생기면 이 config에 EMBED_DIM/EMBED_COLS를 늘려서 fusion으로 확장한다
# (seed/docs/model_architecture.md "다음 단계" 참고).

from pathlib import Path

# seed/scoring/config.py -> parent 3번 = 저장소 루트.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# inference/segment_features.py 출력(device_ifa, z_0..z_31) — seed+pool+candidate 전부 포함.
EMBEDDINGS_CSV = PROJECT_ROOT / "data" / "models" / "segment_features" / "segment_embeddings.csv"

# population 구분용 device_ifa 목록 — 각 쿼리가 이미 정확히 이 population을 정의해뒀으므로
# device_ifa 컬럼만 읽어 멤버십 확인에 쓴다.
SEED_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "04c_seed_segment.csv"
POOL_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "05c_pool_segment.csv"
CANDIDATE_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "07c_candidate_segment.csv"

ID_COL = "device_ifa"
EMBED_DIM = 32
EMBED_COLS = [f"z_{i}" for i in range(EMBED_DIM)]

ARTIFACT_DIR = PROJECT_ROOT / "data" / "models" / "lookalike_classifier"
MODEL_PATH = ARTIFACT_DIR / "model.pt"

HIDDEN_DIM = 32
DROPOUT = 0.2

VAL_SPLIT = 0.1
BATCH_SIZE = 1024
NUM_EPOCHS = 20
LEARNING_RATE = 1e-3
