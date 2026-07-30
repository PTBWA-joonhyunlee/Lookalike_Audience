# Lookalike_Audience

특정 광고에 반응(postback)했거나 관심을 보인 유저와 비슷한 신규 유저를 임베딩 기반으로
찾아내는 프로젝트. 데이터 소스는 propfit(`abi_bid_log_flatten` bid log + `propfit.skp`
세그먼트) — 이 repo에는 Athena 접근 권한이 없어 SQL을 작성하면 사용자가 콘솔에서 직접
실행하고 결과 CSV를 넘겨주는 방식으로 진행한다(자세한 규칙은 [`CLAUDE.md`](CLAUDE.md)).

## 폴더 구조

접근 방식(트랙)별로 폴더를 분리한다 — 각 폴더가 데이터 추출 쿼리 + 파이썬 코드 + 실행
문서를 전부 담은 독립 작업 단위다.

| 폴더 | 내용 |
|---|---|
| [`seed/`](seed/README.md) | 외부 브랜드 seed 리스트(현재: 피엘라벤) 기반 신규 유저 룩어라이크 — 현재 진행 중인 트랙 |
| [`postback/`](postback/README.md) | postback 로그 기반 트랙 — 아직 착수 전(placeholder) |
| [`eda/`](eda/docs/README.md) | 위 트랙들의 피처/쿼리를 확정하기까지의 진단·EDA(ID 공간 크로스워크, 세그먼트 분포, 표본 버그 등) |

`seed/`, `postback/` 각각은 **독립 작업 루트**다 — 저장소 루트가 아니라 해당 폴더로 `cd`
한 뒤 파이썬을 실행한다(가상환경(`.venv`)은 저장소 루트에 하나만 있고, 상대 경로로
참조한다). 자세한 실행법은 각 폴더의 README 참고.

## 환경 설정

`.venv`가 저장소 루트에 있다. 새로 만들어야 하면:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-cpu.txt   # GPU 없는 환경
.venv\Scripts\python.exe -m pip install -r requirements-gpu.txt   # GPU(NVIDIA CUDA) 환경
```

## data/

쿼리 결과 CSV / 임베딩 / 모델 아티팩트 — git 추적 안 됨(`.gitignore`), `seed/`/`postback/`이
공유하는 위치로 저장소 루트에 그대로 둔다.
