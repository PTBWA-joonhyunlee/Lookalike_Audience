# embedding/media_sequence/config.py
#
# 입력 스키마는 querys/audience-embedding-similarity/01_top500_media_visit.sql의 출력과 맞춘다.
# (이벤트 그레인: req_user_id, media, ts, ... — "단기간 재방문" 필터링은 이미 01.sql에서
# 끝난 상태라, 여기서는 req_user_id로 묶어 ts 순서대로 나열하기만 하면 시퀀스가 된다.)

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 01_top500_media_visit.sql 결과 CSV 위치 (data/top500*.csv)
DATA_DIR = PROJECT_ROOT / "data"
DATA_GLOB = "top500*.csv"

ARTIFACT_DIR = PROJECT_ROOT / "data" / "models" / "media_sequence"   # model.pt / vocab_media.json
EMBEDDINGS_DIR = PROJECT_ROOT / "data" / "embeddings"

ID_COL = "req_user_id"
MEDIA_COL = "media"
TS_COL = "ts"
CONTENT_GENRE_COL = "content_genre"
AD_TYPE_COL = "ad_type"
CONNECTION_TYPE_COL = "connection_type"

# top500_media_visit(01)이 이미 상위 500개 미디어로 제한하므로 카디널리티가 낮다.
# min_freq=1(전부 포함), max_size는 방어적 상한만 둔다.
MIN_FREQ = 1
MAX_VOCAB_SIZE = 500

# content_genre는 콤마로 구분된 다중 장르 문자열(예: "Travel,Style & Fashion,...")이라
# 통짜 문자열이 아니라 개별 장르 토큰 단위로 vocab을 만든다 (side_features.split_genres).
GENRE_DELIM = ","
MAX_GENRES_PER_EVENT = 10  # 이벤트 1건당 최대 몇 개 장르까지 쓸지(콤마 분리 후 앞에서부터 자름)

# 보조 피처(content_genre/ad_type/connection_type) vocab. media보다 카디널리티가 훨씬
# 낮을 것으로 예상되지만 정확한 상한을 알 수 없어 방어적으로 넉넉히 잡는다.
SIDE_FEATURE_MIN_FREQ = 1
CONTENT_GENRE_MAX_VOCAB_SIZE = 200
AD_TYPE_MAX_VOCAB_SIZE = 20
CONNECTION_TYPE_MAX_VOCAB_SIZE = 20

MAX_SEQ_LEN = 50     # 유저당 최근 N스텝만 사용 (그보다 길면 앞부분을 자름)
MIN_SEQ_LEN = 5      # 이벤트가 이보다 적은 유저는 학습에서 제외(다음-아이템 예측 신호가 너무 약함).
                      # inference/media_sequence.py도 동일 기준으로 임베딩 자체를 제외한다
                      # (신뢰하기 어려운 임베딩이 lookalike 스코어링에 섞이지 않도록).

EMBED_DIM = 64
N_HEADS = 2
N_LAYERS = 2
FFN_DIM = 128
DROPOUT = 0.2

BATCH_SIZE = 128
NUM_EPOCHS = 30
LEARNING_RATE = 1e-3
