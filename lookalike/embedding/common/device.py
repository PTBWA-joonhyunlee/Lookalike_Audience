# embedding/common/device.py
#
# train/*.py --device (또는 config의 device 키)를 실제 torch.device로 변환한다.
# "auto"(기본값)면 cuda 사용 가능 여부를 보고 고른다.

import torch


def resolve_device(name: str = "auto") -> torch.device:
    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("--device cuda가 지정됐지만 이 환경에서 CUDA를 사용할 수 없습니다.")
    return device
