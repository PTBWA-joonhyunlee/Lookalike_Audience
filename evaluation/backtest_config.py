# evaluation/backtest_config.py
#
# backtest.py의 --config가 가리키는 JSON 설정 파일을 읽는다.
# 스키마는 config/backtest.example.json 참고.

from pathlib import Path
from typing import Any, Dict, Union

from embedding.common.config_file import load_json_config

KNOWN_KEYS = {
    "scored",
    "score_col",
    "scored_id_col",
    "labels",
    "label_col",
    "label_id_col",
    "label_threshold",
    "id_map",
    "map_from_col",
    "map_to_col",
    "n_buckets",
    "output",
}


def load_backtest_config(path: Union[str, Path]) -> Dict[str, Any]:
    return load_json_config(path, KNOWN_KEYS)
