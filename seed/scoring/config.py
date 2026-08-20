# seed/scoring/config.py
#
# seed=1 / pool=0 라벨로 학습하는 지도학습 lookalike 분류기. 입력 임베딩을 segment 단독/
# media 단독/segment+media 결합(concat) 3가지 중 골라 쓸 수 있도록 VARIANTS로 묶었다
# (2026-07-31, 세 가지 결과 비교 요청). segment는
# 기존 MVP(2026-07-30)와 완전히 같은 경로/차원을 그대로 쓴다 — 재학습 없이 결과를 비교에
# 바로 쓸 수 있게.

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# seed/scoring/config.py -> parent 3번 = 저장소 루트.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# population 구분용 device_ifa 목록 — 각 쿼리가 이미 정확히 이 population을 정의해뒀으므로
# device_ifa 컬럼만 읽어 멤버십 확인에 쓴다.
#
# 2026-08-04(segment/media 트랙 분리): segment와 media는 이제 서로 다른 pool/candidate
# 정의를 쓴다(예: media pool은 KR/Android+최소활동량 필터가 있고 5%가 아니라 20% 표본 —
# seed/queries/media/02_pool_media.sql 참고). 예전에는 "media" variant도 이 segment 쪽
# ID 목록으로 seed=1/pool=0 라벨을 매겼는데(=media 단독이라면서도 실제로는 segment∩media
# 교집합으로 학습된 셈), 트랙을 완전히 분리하면서 media 전용 ID 목록을 따로 둔다 —
# Variant.seed_ids_csv/pool_ids_csv/candidate_ids_csv 참고.
SEED_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "seed_segment.csv"
POOL_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "pool_segment.csv"
CANDIDATE_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "candidate_segment.csv"

# je 신규 seed(2026-08-19) — pool/candidate는 피엘라벤 트랙 것을 그대로 재사용(je가
# 1,922명뿐이라 pool을 새로 뽑을 필요가 없다는 판단), seed만 je로 교체.
SEED_JE_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "seed_segment_je.csv"

MEDIA_SEED_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "seed_media.csv"
MEDIA_POOL_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "pool_media.csv"
MEDIA_CANDIDATE_IDS_CSV = PROJECT_ROOT / "data" / "seed" / "candidate_media.csv"

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
    # seed=1/pool=0 라벨 매길 때 쓰는 population 목록, candidate 스코어링 기본 대상 —
    # 트랙마다 pool/candidate 정의가 달라(위 주석 참고) variant별로 분리해서 든다.
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
    "media": Variant(
        name="media",
        sources=[(MEDIA_EMBEDDINGS_CSV, MEDIA_EMBED_COLS)],
        artifact_dir=PROJECT_ROOT / "data" / "models" / "lookalike_classifier_media",
        seed_ids_csv=MEDIA_SEED_IDS_CSV,
        pool_ids_csv=MEDIA_POOL_IDS_CSV,
        candidate_ids_csv=MEDIA_CANDIDATE_IDS_CSV,
    ),
    "combined": Variant(
        name="combined",
        sources=[(SEGMENT_EMBEDDINGS_CSV, SEGMENT_EMBED_COLS), (MEDIA_EMBEDDINGS_CSV, MEDIA_EMBED_COLS)],
        artifact_dir=PROJECT_ROOT / "data" / "models" / "lookalike_classifier_combined",
        # segment/media 트랙이 갈라지며 combined는 더 이상 유효한 조합이 아닐 수 있다
        # (두 트랙의 pool/candidate 모집단 정의 자체가 달라짐) — 당장 쓸 계획이 없다면
        # VARIANTS에서 이 항목을 빼는 것도 검토할 것. ID 목록은 우선 segment 쪽을 씀.
        seed_ids_csv=SEED_IDS_CSV,
        pool_ids_csv=POOL_IDS_CSV,
        candidate_ids_csv=CANDIDATE_IDS_CSV,
    ),
}
