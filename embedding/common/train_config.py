# embedding/common/train_config.py
#
# train/*.py의 --config가 가리키는 JSON 설정 파일을 읽는다.
# 스키마는 config/train_config.example.json 참고.

from pathlib import Path
from typing import Any, Dict, Union

from .config_file import load_json_config

KNOWN_KEYS = {"dataset_path", "output_model_path", "num_epochs", "batch_size", "learning_rate"}


def load_train_config(path: Union[str, Path]) -> Dict[str, Any]:
    return load_json_config(path, KNOWN_KEYS)
