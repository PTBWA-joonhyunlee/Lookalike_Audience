# embedding/common/inference_config.py
#
# inference/*.py의 --config가 가리키는 JSON 설정 파일을 읽는다.
# 스키마는 config/inference_config.example.json 참고.

from pathlib import Path
from typing import Any, Dict, Union

from .config_file import load_json_config

KNOWN_KEYS = {"dataset_path", "output_path", "model_dir"}


def load_inference_config(path: Union[str, Path]) -> Dict[str, Any]:
    return load_json_config(path, KNOWN_KEYS)
