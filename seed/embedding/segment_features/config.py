# seed/embedding/segment_features/config.py
#
# 입력 스키마는 seed/queries/lib/11_user_embedding_features.sql의 출력과 맞춘다.
# skp 세그먼트 기반 임베딩 피처(성별 스칼라/연령대 원핫/거주·관심사 BERT 풀링) 전용.

from pathlib import Path

# seed/embedding/segment_features/config.py -> parent 4번 = 저장소 루트(seed/의 상위).
# data/는 seed/postback이 공유하는 top-level 위치라 seed/ 안으로 옮기지 않았다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 11_user_embedding_features.sql 결과 CSV 위치 — seed/pool/candidate 세 population의
# *_segment.csv(04c_seed_segment.csv/05c_pool_segment.csv/07c_candidate_segment.csv)를
# 전부 glob해서 하나로 합친다. build_features.py는 population 구분 없이 피처 인코딩만
# 하고(device_ifa 키로 나중에 어느 population인지 다시 매핑), 여기서 합쳐 만든 하나의
# age_vocab/피처 배열을 세 population이 공유한다.
DATA_DIR = PROJECT_ROOT / "data" / "seed"
DATA_GLOB = "*_segment.csv"

# 세그먼트 ID -> 카테고리 경로 텍스트 매핑 원본(Athena 테이블 아님, 로컬 정적 참조 파일).
SEGMENT_CATEGORY_CSV = PROJECT_ROOT / "data" / "seed" / "세그먼트_카테고리.csv"

ARTIFACT_DIR = PROJECT_ROOT / "data" / "models" / "segment_features"
# segment_id -> 768dim 벡터 lookup 캐시(최초 1회 생성 후 재사용, taxonomy 안 바뀌면 재계산 불필요)
BERT_LOOKUP_PATH = ARTIFACT_DIR / "segment_bert_lookup.npz"
AGE_VOCAB_PATH = ARTIFACT_DIR / "age_bracket_vocab.json"

ID_COL = "device_ifa"

# 사전학습 한국어 문장임베딩 모델. 거주/제품 관심사/콘텐츠 관심사/기타 전부 같은 lookup을
# 공유한다(2026-07-24 결정: "관심사 3그룹은 공유 임베딩 공간 + 그룹별 분리 풀링").
BERT_MODEL_NAME = "jhgan/ko-sroberta-multitask"
BERT_EMBED_DIM = 768

# 풀링 대상 컬럼(세미콜론 구분 segment_id 문자열) — 각각 독립적으로 mean pooling한다.
POOLED_ID_COLUMNS = {
    "residence": "residence_ids",              # 하나의 bag(쪼개지 않음, 2026-07-24 결정)
    "product_interest": "product_interest_ids",
    "content_interest": "content_interest_ids",
    "etc_segment": "etc_segment_ids",
}

# 그룹별 최대 태그 개수(초과분은 뒤에서부터 자름) — 11_user_embedding_features.sql 1% 표본
# (53만 건, 2026-07-24) 기준 p99에 여유를 두고 반올림한 값. 실제 규모/taxonomy가 바뀌면
# data/seed/*_segment.csv로 다시 분포 확인 후 조정할 것.
#   residence p99=65, product_interest p99=21, content_interest p99=48, etc_segment p99=41
POOLED_MAX_LEN = {
    "residence": 72,
    "product_interest": 24,
    "content_interest": 48,
    "etc_segment": 48,
}

GENDER_SCORE_COL = "gender_score"      # SQL에서 이미 계산된 스칼라, 그대로 통과
AGE_BRACKET_ID_COL = "age_bracket_ids"  # 세미콜론 구분, 보통 0~1개 -> 첫 값만 사용

# ---- Autoencoder 하이퍼파라미터 (seed/docs/model_architecture.md) ----
AGE_EMBED_DIM = 8   # 카테고리 필드용 소규모 임베딩 차원

# 그룹별 768dim pooled 벡터를 concat 전에 투영하는 차원 — "그룹이 담는 정보량"(카디널리티/
# max_len)에 대략 비례하게 잡음. 그대로 두면 768dim이 나머지 필드(1~8dim)를 압도해버린다.
PROJ_DIMS = {
    "residence": 32,
    "product_interest": 16,
    "content_interest": 16,
    "etc_segment": 16,
}

FREEZE_BERT_LOOKUP = False   # False면 학습 중 세그먼트 벡터도 파인튜닝됨(BERT 자체를 재실행하진 않음)
HIDDEN_DIM = 64
EMBED_DIM = 32   # z(segment_features 임베딩) 차원 — 원본 신호가 단순해 작게 둠, 확정값 아님

BATCH_SIZE = 512
NUM_EPOCHS = 30
LEARNING_RATE = 1e-3

MODEL_PATH = ARTIFACT_DIR / "model.pt"
