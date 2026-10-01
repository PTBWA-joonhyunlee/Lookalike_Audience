# seed/scoring/config.py
#
# seed=1 / pool=0 라벨로 학습하는 지도학습 lookalike 분류기. segment 임베딩 기반
# variant를 VARIANTS로 묶어 seed 브랜드마다 골라 쓴다. segment는 기존 MVP(2026-07-30)와
# 완전히 같은 경로/차원을 그대로 쓴다 — 재학습 없이 결과를 비교에 바로 쓸 수 있게.
#
# 2026-08-26: media/combined variant와 media 트랙 코드(embedding/media_sequence,
# queries/media/, train·inference의 media_sequence.py)를 전부 제거했다(자세한 배경은
# git 히스토리 참고) — 이제 segment 단독 variant만 쓴다.

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# seed/scoring/config.py -> parent 3번 = 저장소 루트.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# population 구분용 device_ifa 목록 — 각 쿼리가 이미 정확히 이 population을 정의해뒀으므로
# device_ifa 컬럼만 읽어 멤버십 확인에 쓴다.
SEED_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "seed_segment.csv"
POOL_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "pool_segment.csv"
CANDIDATE_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "candidate_segment.csv"

# je 신규 seed(2026-08-19) — pool/candidate는 피엘라벤 트랙 것을 그대로 재사용(je가
# 1,922명뿐이라 pool을 새로 뽑을 필요가 없다는 판단), seed만 je로 교체.
SEED_JE_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "seed_segment_je.csv"

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


VARIANTS = {
    "segment": Variant(
        name="segment",
        sources=[(SEGMENT_EMBEDDINGS_CSV, SEGMENT_EMBED_COLS)],
        artifact_dir=PROJECT_ROOT / "data" / "models" / "lookalike_classifier",
        seed_ids_csv=SEED_IDS_CSV,
        pool_ids_csv=POOL_IDS_CSV,
        candidate_ids_csv=CANDIDATE_IDS_CSV,
    ),
    "segment_je": Variant(
        name="segment_je",
        # inference/segment_features.py 출력(SEGMENT_EMBEDDINGS_CSV)에 je seed 임베딩 행을
        # append해서 재사용한다(seed/docs 안내 참고) — 피엘라벤 seed 행이 섞여 있어도
        # build_labeled_frame이 seed_ids_csv/pool_ids_csv로만 라벨을 매기므로 무해하다.
        sources=[(SEGMENT_EMBEDDINGS_CSV, SEGMENT_EMBED_COLS)],
        artifact_dir=PROJECT_ROOT / "data" / "models" / "lookalike_classifier_je",
        seed_ids_csv=SEED_JE_IDS_CSV,
        pool_ids_csv=POOL_IDS_CSV,
        candidate_ids_csv=CANDIDATE_IDS_CSV,
    ),
}


# ---------- 멀티라벨(멀티헤드) 분류기 ----------
# 2026-09-28: 서로 겹치는 seed 여러 개(군 관련 4종 — 쌍별로 13~26% 겹침)를 seed별 이진
# 분류기 4개 대신 공유 trunk + 라벨별 sigmoid 헤드 하나로 같이 학습한다. 라벨은 seed 소속
# 멀티핫(여러 seed에 속하면 여러 개가 1), pool에만 있는 유저는 전부 0.

# 헤드 여러 개가 trunk를 공유하므로 이진 분류기(HIDDEN_DIM=32)보다 약간 넓게 둔다.
MULTILABEL_HIDDEN_DIM = 64

@dataclass
class Label:
    key: str            # 파일/컬럼명용 영문 키(score_<key> 등)
    description: str    # 사람이 읽는 라벨 설명(결과 메타데이터용 — 학습에는 안 씀)
    seed_ids_csv: Path


@dataclass
class MultiLabelVariant:
    name: str
    labels: List[Label]
    sources: List[Tuple[Path, List[str]]]
    artifact_dir: Path
    pool_ids_csv: Path
    candidate_ids_csv: Path

    @property
    def label_keys(self) -> List[str]:
        return [lb.key for lb in self.labels]

    @property
    def embed_cols(self) -> List[str]:
        return [c for _, cols in self.sources for c in cols]

    @property
    def embed_dim(self) -> int:
        return len(self.embed_cols)

    @property
    def model_path(self) -> Path:
        return self.artifact_dir / "model.pt"

    @property
    def labels_path(self) -> Path:
        return self.artifact_dir / "labels.json"


_SEED_DATA_DIR = PROJECT_ROOT / "data" / "seed"

MULTILABEL_VARIANTS = {
    # 군 관련 seed 4종(2026-09-28 온보딩, id space 전부 direct). candidate는 4종 + 기존 seed
    # 전부를 제외한 2026-06-01~09-25 bid log 모집단(segment/04_candidate_segment_parents.sql —
    # 파일명은 parents지만 4종 공용).
    "military": MultiLabelVariant(
        name="military",
        labels=[
            Label("discharged_male", "전역한 남성", _SEED_DATA_DIR / "seed_segment_discharged_male.csv"),
            Label("parents", "아들을 군대에 보낸 부모", _SEED_DATA_DIR / "seed_segment_parents.csv"),
            Label("gomsin", "남자친구의 전역을 기다리는 여자친구", _SEED_DATA_DIR / "seed_segment_gomsin.csv"),
            Label("enlistee", "입대예정 남성", _SEED_DATA_DIR / "seed_segment_enlistee.csv"),
        ],
        sources=[(SEGMENT_EMBEDDINGS_CSV, SEGMENT_EMBED_COLS)],
        artifact_dir=PROJECT_ROOT / "data" / "models" / "lookalike_multilabel_military",
        pool_ids_csv=POOL_IDS_CSV,
        candidate_ids_csv=_SEED_DATA_DIR / "candidate_segment_20260928.csv",
    ),
}
