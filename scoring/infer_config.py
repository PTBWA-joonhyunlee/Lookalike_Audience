# scoring/infer_config.py
#
# infer_supervised_lookalike.py의 --config가 가리키는 JSON 설정 파일을 읽는다.
# 스키마는 config/infer_supervised_lookalike.example.json 참고.

from pathlib import Path
from typing import Any, Dict, Union

from embedding.common.config_file import load_json_config

KNOWN_KEYS = {
    "model_dir",
    "target_profile_emb",
    "target_media_emb",
    "output",
    "id_col",
}


def load_infer_config(path: Union[str, Path]) -> Dict[str, Any]:
    return load_json_config(path, KNOWN_KEYS)
