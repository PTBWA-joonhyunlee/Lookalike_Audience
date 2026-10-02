# lookalike/scoring/config.py
#
# seed=1 / pool=0 라벨로 학습하는 지도학습 lookalike 분류기의 공용 설정. 경로/variant는
# 파이프라인(pipeline/run_seed_scenario1.py)이 실행마다 Variant를 즉석에서 만든다.

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# lookalike/scoring/config.py -> parent 3번 = 저장소 루트.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

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


@dataclass
class Variant:
    name: str
    # [(csv_path, embed_cols), ...] — 지금은 항상 1개(segment 임베딩)만 쓴다.
    sources: List[Tuple[Path, List[str]]]
    artifact_dir: Path
    # seed=1/pool=0 라벨 매길 때 쓰는 population 목록, candidate 스코어링 기본 대상 —
    # seed 브랜드마다 pool/candidate 정의가 달라질 수 있어 variant별로 분리해서 든다.
    seed_ids_csv: Path
    pool_ids_csv: Path
    candidate_ids_csv: Path

    @property
    def embed_cols(self) -> List[str]:
        return [c for _, cols in self.sources for c in cols]

    @property
    def embed_dim(self) -> int:
        return len(self.embed_cols)

    @property
    def model_path(self) -> Path:
        return self.artifact_dir / "model.pt"
