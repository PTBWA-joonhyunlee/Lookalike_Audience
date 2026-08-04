# seed/embedding/media_sequence/config.py
#
# 입력 스키마는 seed/queries/lib/02_user_media.sql(및 seed/queries/media/02~05_*.sql)의
# 출력과 맞춘다. 옛 addi 트랙 embedding/media_sequence/config.py를 propfit 스키마로 이식 —
# content_genre 컬럼이 없는 대신 inventory_type(app/site)이 있어 이걸 ad_type/connection_type과
# 같은 단일값 보조 피처로 다룬다(dataset.py/model.py 헤더 참고).

from pathlib import Path

# seed/embedding/media_sequence/config.py -> parent 4번 = 저장소 루트(seed/의 상위).
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# seed_media.csv / pool_media.csv (이벤트 그레인, 합쳐서 최대 14GB) — build_features.py가
# 청크 단위로 스트리밍 처리한다(전체를 한 번에 메모리에 올리지 않음). 기본 학습 대상은 이
# 둘뿐이다 — candidate_media.csv(media/05_candidate_media.sql 출력, 스코어링 대상
# population)는 여기 포함시키지 않는다(--reuse-vocab --input으로 별도 처리, train.media_sequence
# 실행 안내 참고) — vocab을 candidate로 오염시키지 않고, 학습 손실도 순수 seed/pool
# 다음-아이템 예측에만 집중시키기 위함(2026-08-04 segment/media 트랙 분리 이후 명시적으로
# 파일명을 나열, 이전엔 "*_media.csv" 글롭이 우연히 seed/pool/구candidate 3개만
# 매칭했었다 — candidate_media.csv도 이름이 같은 패턴이라 이제는 명시적 목록이 필요).
DATA_DIR = PROJECT_ROOT / "data" / "seed"
DATA_FILES = ["seed_media.csv", "pool_media.csv"]

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

# seed/queries/media/01_create_media_vocab_table.sql이 이미 전체 모집단 기준 top500으로
# media를 제한해뒀으므로 카디널리티가 낮다. min_freq=1(전부 포함), max_size는 방어적
# 상한만 둔다.
MIN_FREQ = 1
MAX_VOCAB_SIZE = 500

SIDE_FEATURE_MIN_FREQ = 1
INVENTORY_TYPE_MAX_VOCAB_SIZE = 10   # app/site 2종 + <NA>/<UNK>
AD_TYPE_MAX_VOCAB_SIZE = 20
CONNECTION_TYPE_MAX_VOCAB_SIZE = 20

MAX_SEQ_LEN = 50     # 유저당 최근 N스텝만 사용(그보다 길면 앞부분을 자름)
MIN_SEQ_LEN = 5      # 이벤트가 이보다 적은 유저는 학습/추론 임베딩에서 제외
                      # (다음-아이템 예측 신호가 너무 약해 신뢰하기 어려움)

# 2026-08-03 추가(TiSASRec 스타일 position + 시간대 side feature): 기존 position_embedding은
# 순서(0..49)만 알고 실제 얼마나 시간이 흘렀는지 모른다는 한계가 있어, position을 "직전
# 이벤트와의 시간 간격" 버킷으로 재정의한다(model.py 참고). 여기에 절대 시간대(3시간
# 단위)는 정보가 달라(간격=재방문 리듬, 시간대=습관적 이용 시간) 별도 side feature로
# 추가한다 — inventory_type/ad_type/connection_type과 동일 패턴.
#
# 시간 간격 버킷: 경계값(초) 8개 -> 9구간(<5분/5~30분/30분~1시간/1~3시간/3~6시간/6~12시간/
# 12~24시간/1~3일/3일 이상). 인코딩: 0=pad, 1=첫 이벤트(직전 이벤트 없음), 2~10=구간.
TIME_GAP_BOUNDARIES_SEC = [300, 1800, 3600, 10800, 21600, 43200, 86400, 259200]
TIME_GAP_VOCAB_SIZE = len(TIME_GAP_BOUNDARIES_SEC) + 1 + 2  # 구간 9 + 첫이벤트 1 + pad 1 = 11

# 절대 시간대 버킷: 3시간 단위 8구간(00-03시, 03-06시, ..., 21-24시, ts는 이미 SQL에서
# Asia/Seoul로 변환된 로컬 시각). 인코딩: 0=pad, 1~8=구간.
TIME_OF_DAY_BUCKET_HOURS = 3
TIME_OF_DAY_VOCAB_SIZE = 24 // TIME_OF_DAY_BUCKET_HOURS + 1  # 구간 8 + pad 1 = 9

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
