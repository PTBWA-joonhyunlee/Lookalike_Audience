# embedding/common/config_file.py
#
# train/*.py --config, inference/*.py --config가 공통으로 쓰는 JSON 설정 파일 로더.
# 알려진 키만 취해서 반환하고(모듈마다 필요한 키가 달라 스키마를 강제하지 않는다), 그 외
# 키는 `_`로 시작하면(주석 용도, 예: "_comment") 조용히 무시하고 그 외에는 경고만 낸다.

import json
from pathlib import Path
from typing import Any, Dict, Set, Union


def load_json_config(path: Union[str, Path], known_keys: Set[str]) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    comment_keys = {k for k in raw if k.startswith("_")}
    unknown = set(raw) - known_keys - comment_keys
    if unknown:
        print(f"[WARN] {path}에 알 수 없는 키(무시됨): {sorted(unknown)}")

    return {k: v for k, v in raw.items() if k in known_keys}
