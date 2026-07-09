# scoring/train_config.py
#
# train_supervised_lookalike.py의 --config가 가리키는 JSON 설정 파일을 읽는다.
# 스키마는 config/train_supervised_lookalike.example.json 참고.

from pathlib import Path
from typing import Any, Dict, Union

from embedding.common.config_file import load_json_config

KNOWN_KEYS = {
    "pool_profile_emb",
    "pool_media_emb",
    "seed_ids",
    "model_out",
    "id_col",
    "num_epochs",
    "batch_size",
    "learning_rate",
    "pos_frac",
    "topk_pct",
}


def load_train_config(path: Union[str, Path]) -> Dict[str, Any]:
    return load_json_config(path, KNOWN_KEYS)
