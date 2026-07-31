# seed/scoring/config.py
#
# seed=1 / pool=0 라벨로 학습하는 지도학습 lookalike 분류기. 입력 임베딩을 segment 단독/
# media 단독/segment+media 결합(concat) 3가지 중 골라 쓸 수 있도록 VARIANTS로 묶었다
# (2026-07-31, 세 가지 결과 비교 요청 — seed/docs/model_architecture.md 참고). segment는
# 기존 MVP(2026-07-30)와 완전히 같은 경로/차원을 그대로 쓴다 — 재학습 없이 결과를 비교에
# 바로 쓸 수 있게.

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# seed/scoring/config.py -> parent 3번 = 저장소 루트.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# population 구분용 device_ifa 목록 — 각 쿼리가 이미 정확히 이 population을 정의해뒀으므로
# device_ifa 컬럼만 읽어 멤버십 확인에 쓴다.
SEED_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "04c_seed_segment.csv"
POOL_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "05c_pool_segment.csv"
CANDIDATE_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "07c_candidate_segment.csv"

ID_COL = "device_ifa"
HIDDEN_DIM = 32
DROPOUT = 0.2

VAL_SPLIT = 0.1
BATCH_SIZE = 1024
NUM_EPOCHS = 20
LEARNING_RATE = 1e-3

# inference/segment_features.py 출력(device_ifa, z_0..z_31) — seed+pool+candidate 전부 포함.
SEGMENT_EMBEDDINGS_CSV = PROJECT_ROOT / "data" / "models" / "segment_features" / "segment_embeddings.csv"
SEGMENT_EMBED_COLS = [f"z_{i}" for i in range(32)]

# inference/media_sequence.py 출력(device_ifa, m_0..m_63) — 이벤트 5개 미만 디바이스는
# 빠져 있다(embedding/media_sequence/config.MIN_SEQ_LEN 참고).
MEDIA_EMBEDDINGS_CSV = PROJECT_ROOT / "data" / "models" / "media_sequence" / "media_embeddings.csv"
MEDIA_EMBED_COLS = [f"m_{i}" for i in range(64)]


@dataclass
class Variant:
    name: str
    # [(csv_path, embed_cols), ...] — 1개면 그 임베딩만, 2개면 device_ifa 기준 inner join
    # 후 컬럼을 이어붙인다(둘 다 있는 디바이스만 남음 — combined의 표본이 media 커버리지
    # 만큼 줄어드는 이유, 비교 결과 정리 시 반드시 같이 밝힐 것).
    sources: List[Tuple[Path, List[str]]]
    artifact_dir: Path

    @property
    def embed_cols(self) -> List[str]:
        return [c for _, cols in self.sources for c in cols]

    @property
    def embed_dim(self) -> int:
        return len(self.embed_cols)

    @property
    def model_path(self) -> Path:
        return self.artifact_dir / "model.pt"


VARIANTS = {
    "segment": Variant(
        name="segment",
        sources=[(SEGMENT_EMBEDDINGS_CSV, SEGMENT_EMBED_COLS)],
        artifact_dir=PROJECT_ROOT / "data" / "models" / "lookalike_classifier",
    ),
    "media": Variant(
        name="media",
        sources=[(MEDIA_EMBEDDINGS_CSV, MEDIA_EMBED_COLS)],
        artifact_dir=PROJECT_ROOT / "data" / "models" / "lookalike_classifier_media",
    ),
    "combined": Variant(
        name="combined",
        sources=[(SEGMENT_EMBEDDINGS_CSV, SEGMENT_EMBED_COLS), (MEDIA_EMBEDDINGS_CSV, MEDIA_EMBED_COLS)],
        artifact_dir=PROJECT_ROOT / "data" / "models" / "lookalike_classifier_combined",
    ),
}
