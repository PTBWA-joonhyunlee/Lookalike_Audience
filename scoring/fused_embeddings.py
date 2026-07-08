# scoring/fused_embeddings.py
#
# user_profile/media_sequence 임베딩 CSV 2개를 req_user_id로 합쳐 fused 벡터를 만드는 공용
# 유틸리티. train_supervised_lookalike.py/infer_supervised_lookalike.py가 공유한다.

import pandas as pd

ID_COL = "req_user_id"


def load_fused_embeddings(profile_path: str, media_path: str, id_col: str = ID_COL) -> pd.DataFrame:
    """user_profile/media_sequence 임베딩 CSV 2개를 req_user_id로 inner join해서 하나의
    DataFrame(id_col + emb_00..emb_127)으로 합친다. 두 임베딩이 다 있는 유저만 남는다 —
    한쪽만 있으면(예: 프로필은 있는데 방문 이벤트가 top500 필터에 하나도 안 걸린 경우)
    fused 벡터를 만들 수 없으므로 제외한다."""
    profile = pd.read_csv(profile_path)
    media = pd.read_csv(media_path)
    merged = profile.merge(media, on=id_col, suffixes=("_profile", "_media"))
    return merged
