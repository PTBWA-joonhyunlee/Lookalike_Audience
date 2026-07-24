# embedding/segment_features/config.py
#
# 입력 스키마는 querys/propfit/11_user_embedding_features.sql의 출력과 맞춘다.
# skp 세그먼트 기반 임베딩 피처(성별 스칼라/연령대 원핫/거주·관심사 BERT 풀링) 전용 —
# 기존 embedding/user_profile, embedding/media_sequence(addi 소스)과는 별개 트랙.

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 11_user_embedding_features.sql 결과 CSV 위치
DATA_DIR = PROJECT_ROOT / "data" / "propfit"
DATA_GLOB = "11_user_embedding_features*.csv"

# 세그먼트 ID -> 카테고리 경로 텍스트 매핑 원본(Athena 테이블 아님, 로컬 정적 참조 파일).
SEGMENT_CATEGORY_CSV = PROJECT_ROOT / "data" / "sample" / "세그먼트_카테고리.csv"

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
# data/propfit/11_user_embedding_features*.csv로 다시 분포 확인 후 조정할 것.
#   residence p99=65, product_interest p99=21, content_interest p99=48, etc_segment p99=41
POOLED_MAX_LEN = {
    "residence": 72,
    "product_interest": 24,
    "content_interest": 48,
    "etc_segment": 48,
}

GENDER_SCORE_COL = "gender_score"      # SQL에서 이미 계산된 스칼라, 그대로 통과
AGE_BRACKET_ID_COL = "age_bracket_ids"  # 세미콜론 구분, 보통 0~1개 -> 첫 값만 사용
