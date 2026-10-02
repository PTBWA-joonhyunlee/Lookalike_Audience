# Lookalike_Audience

외부 seed 리스트(광고 ID)와 비슷한 신규 유저를 임베딩 기반으로 찾아내는 프로젝트. 데이터 소스는
propfit(`abi_bid_log_flatten` bid log + `propfit.skp` 세그먼트). Athena/S3는 boto3로 직접 호출한다
(규칙은 [`CLAUDE.md`](CLAUDE.md)).

## 폴더 구조

| 폴더 | 내용 |
|---|---|
| [`lookalike/`](lookalike/README.md) | 파이프라인 코드 — Athena 실행기, 쿼리 템플릿, 오토인코더/분류기 |
| `config/` | IAM 정책 JSON(`iam/`), 학습 설정 예시, AWS 키(`LAL_accessKeys.csv`, git 제외) |
| [`eda/`](eda/docs/README.md) | 진단·EDA 결과 문서(ID 공간 크로스워크, 표본 버그 등) |
| `data/` | 쿼리 결과 CSV / 임베딩 / 모델 아티팩트 — git 추적 안 됨 |

`lookalike/`는 **독립 작업 루트**다 — 저장소 루트가 아니라 그 폴더로 `cd`한 뒤 파이썬을 실행한다
(가상환경 `.venv`는 저장소 루트에 하나, 상대 경로로 참조).

## 환경 설정

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-cpu.txt   # GPU 없는 환경
.venv\Scripts\python.exe -m pip install -r requirements-gpu.txt   # GPU(NVIDIA CUDA) 환경
.venv\Scripts\python.exe -m pip install boto3
```

AWS 키는 `config/LAL_accessKeys.csv`(헤더 `Access key ID, Secret access key`)에 둔다.
