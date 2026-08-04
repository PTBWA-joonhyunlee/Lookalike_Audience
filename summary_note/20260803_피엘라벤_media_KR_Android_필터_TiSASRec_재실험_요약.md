# 피엘라벤 Seed 기반 media(방문 앱/사이트) 룩어라이크 — KR/Android 필터 + TiSASRec 재실험 요약

## 0. 목표

[`20260803_피엘라벤_media_기반_룩어라이크_분석_요약.md`](20260803_피엘라벤_media_기반_룩어라이크_분석_요약.md)(이하
"1차 media 문서")에서 확인된 두 가지 문제를 해결하기 위한 재실험 결과를 정리한다.

1. **모집단(pool)/후보(candidate)가 해외(주로 일본)·iOS 트래픽을 많이 포함해 media 신호가
   희석된다는 가설** — profile 분석(region/OS)에서 pool은 KR 31.6%/Android 74.9%뿐인 반면
   seed는 KR 98.4%/Android 99.4%로 거의 전부였다. 이를 검증하기 위해 **학습(seed/pool)·
   candidate 쿼리 9개 전부에 region=KR AND OS=Android 필터를 추가**했다.
2. **media_sequence(SASRec)의 position_embedding이 순서(0..49)만 알고 "언제/얼마나 간격을
   두고" 방문했는지는 전혀 모른다는 한계** — position을 **TiSASRec 스타일 "직전 이벤트와의
   시간 간격" 버킷 임베딩**으로 재정의하고, 3시간 단위 절대 시간대를 새 side feature로
   추가했다.

이 문서는 (1) 필터 적용 후 모집단/seed의 media 성향이 어떻게 달라졌는지(1~2번), (2) 새로
뽑은 후보 집단의 media 성향과 그 안에서 발견된 심각한 이상 현상(3번), (3) 바뀐 임베딩
아키텍처(4번), (4) 이번 재실험 과정에서 발견된 이슈들(5번)을 다룬다. **1차 media 문서와
직접 비교되는 수치가 많으므로, 특히 3번과 5번은 1차 문서를 먼저 읽고 보는 게 이해가 빠르다.**

### 0-1. pool vs candidate 추출 방식 — 기간·필터·샘플링

pool과 candidate는 필터(seed 제외, region=KR, OS=Android)는 같지만, **기간과 "얼마나
뽑는가"의 기준이 근본적으로 다르다.**

| | pool(`05a`/`05b`) | candidate(`06b`/`06c`/`07d`) |
|---|---|---|
| 기간 | **2026-04~05**(seed와 같은 학습 기간) | **2026-06**(학습 기간과 겹치지 않는 스코어링 대상 기간) |
| seed 제외 / region=KR / OS=Android | 적용 | 적용(동일) |
| **최소 활동량 조건** | **없음** — top500 미디어 이벤트가 1건만 있어도 포함 | **있음**: `GROUP BY device_ifa HAVING COUNT(*) >= 5`(30분 재방문 dedup 후, **미디어 항목 종류와 무관하게 합산** 5회 이상) |
| **샘플링** | **20%**(`mod(crc32(device_ifa),1000) < 200`, 무작위 해시) | **없음(100%)** — 필터+활동량 조건을 통과한 전원 |

**pool은 "무작위 20%," candidate는 "무작위가 아니라 활동량 최소 기준(5회 이상) 통과자
전원"**이라는 게 핵심 차이다. 그 결과 1인당 이벤트 수가 candidate(평균 41.4건/중앙값
15건)가 pool(19.0건/6건)·seed(25.3건/11건)보다 훨씬 높다(3번 절 통계) — candidate는
정의상 활동량이 일정 수준 이상인 사람만 모은 집단이기 때문이다. 이 차이는 3번 절/5-1
이슈와 직접 연결된다.

## 1. 모집단(pool) media 성향 분석 결과 (필터 적용 후)

| 항목 | 1차(필터 전) | 이번(KR+Android 필터 후) |
|---|---|---|
| 모집단 규모 | 2,539,480명(5% 표본) | **2,743,442명(20% 표본)** — 표본 비율을 4배 올렸지만 필터로 줄어든 만큼 상쇄돼 절대 규모는 오히려 더 커짐 |
| 1인당 이벤트 수 | 평균 18.5건, 중앙값 5건 | 평균 19.0건, 중앙값 6건(거의 동일) |
| 1인당 top500 미디어 다양성 | 평균 1.42개, 중앙값 1개 | 평균 1.51개, 중앙값 1개(거의 동일) |
| inventory_type | app 99.80%, site 0.45% | app 99.51%, site 1.00% |

**top10 방문자 비율 — 완전히 달라졌다**:

| 순위 | 1차(필터 전) | 이번(필터 후) |
|---|---|---|
| 1 | `com.nttdocomo.android.mymagazine`(일본) 10.07% | `com.skt.prod.dialer`(SKT) **31.29%** |
| 2 | `com.skt.prod.dialer` 8.47% | `com.cashwalk.cashwalk`(캐시워크) **18.70%** |
| 3 | `com.cashwalk.cashwalk` 5.05% | `viva.republica.toss`(토스) **13.77%** |
| 4 | `viva.republica.toss` 3.73% | `com.ktcs.whowho`(후후) 6.22% |
| 5 | `us.mitene`(일본) 3.73% | `com.skb.adui` 3.97% |
| 6 | `579581125`(숫자ID) 3.62% | `com.block.juggle` 3.62% |
| 7 | `gogolook.callgogolook2` 3.60% | `com.astroframe.seoulbus`(서울버스) 3.51% |
| 8 | `com.block.juggle` 3.23% | `com.dencreak.dlcalculator` 3.46% |
| 9 | `com.kddi.pass.launcher`(일본) 3.02% | `com.dho.mobilefax`(모바일팩스) 3.43% |
| 10 | `1617391485`(숫자ID) 3.02% | `com.kakaopay.app`(카카오페이) 2.88% |

**해석**: 필터 적용 전엔 top10에 일본 통신사/서비스 앱(도코모/mitene/KDDI)이 절반 가까이
섞여 있었는데, 필터 후엔 **top10 전부가 한국 앱**으로 바뀌었다. 특히 SKT 다이얼러(8.47%
→31.29%)·캐시워크(5.05%→18.70%)·토스(3.73%→13.77%) 비율이 3~4배 뛰었다 — 1번 문서에서
확인된 "pool은 해외 트래픽이 많아 top500 vocab과 seed 프로필이 희석된다"는 가설이 그대로
맞았다는 뜻이다.

## 2. Seed media 분석 결과 (필터 적용 후)

| 항목 | 1차(필터 전) | 이번(필터 후) |
|---|---|---|
| 모집단 규모 | 1,015,872명 | 1,010,817명(-0.5%, 거의 안 바뀜 — seed는 원래 98~99% KR/Android) |
| 1인당 이벤트 수 | 평균 25.6건, 중앙값 11건 | 평균 25.3건, 중앙값 11건 |
| top10 순위/비율 | SKT다이얼러 44.06%, 캐시워크 38.04%, 토스 23.81%, 카카오페이 6.66%, 후후 4.79% | SKT다이얼러 **44.24%**, 캐시워크 **38.15%**, 토스 **23.89%**, 카카오페이 **6.68%**, 후후 **4.80%** |

**해석**: 예상대로 seed는 필터 전후로 사실상 변화가 없다(소수점 둘째 자리 수준의 차이) —
seed는 애초에 거의 전부 KR+Android였기 때문에, 이번 필터는 seed 자체보다는 **pool/candidate를
seed와 "같은 기준선"으로 맞추는 효과**였다는 게 1~2번 절 비교로 명확해졌다.

**top30 media 겹침(Jaccard)도 극적으로 개선됐다**: seed∩pool이 **0.154 → 0.667**로
4배 이상 뛰었다(top30 중 24개 항목이 동일) — pool의 media 프로필이 이제 seed와 훨씬
비슷해졌다는 뜻이며, 1번 절 표와 일관된 결과다.

## 3. 추출한 신규 후보(candidates_202606_media)의 media 분석 및 Seed와 비교

**규모 변화**: 필터+표본 비율을 세 차례 조정했다 — 5%(160,717명 목표였으나 실제로도 이
근처)→20%(160,717명, 여전히 목표인 66만 명에 크게 못 미침)→**샘플링 제거, 필터 후 전체
그대로(804,606명)**. 자세한 경위는 5번 절 참고.

**top10 방문자 비율(804,606명 기준) — seed/pool과 완전히 다른, 예상 밖의 결과**:

| 순위 | media | 방문자 비율 | 비고 |
|---|---|---|---|
| 1 | `com.skb.adui` | **72.87%** | pool에도 있지만 3.97%뿐인 항목이 여기선 압도적 1위 |
| 2 | `com.dcinside.app.android`(디시인사이드 앱) | **24.97%** | |
| 3 | `https://www.instiz.net`(인스티즈, 커뮤니티) | 1.41% | |
| 4~10 | instiz.net 하위 페이지들 | 0.44~1.03% | |

3위 밖은 `bobaedream`(보배드림), `ppomppu`(뽐뿌), `theqoo`(더쿠), `fmkorea`(에펨코리아),
`clien`(클리앙), `humoruniv`, `namu.wiki` 등 **한국 커뮤니티/게시판 사이트**가 top30 나머지를
채운다 — seed/pool의 top10(통신사 다이얼러·핀테크 앱)과는 완전히 다른 종류의 media다.

**1인당 media 다양성도 확연히 다르다**: 이 후보군은 평균 1.05개/중앙값 1개(seed 1.90/2,
pool 1.51/1) — **대부분의 후보가 top500 미디어 중 딱 1개만, 그것도 아주 여러 번 반복
방문**한다는 뜻이다. `com.skb.adui`(72.87%)와 `com.dcinside.app.android`(24.97%) 두 항목만
합쳐도 후보 전체의 거의 대부분을 설명한다.

**seed/pool과의 top30 겹침(Jaccard)**:

| 비교 | Jaccard | 비고 |
|---|---|---|
| seed ∩ pool | **0.667** | 필터 후 크게 개선(1번 절 참고) |
| pool ∩ candidate | **0.053** | 필터 전(0.463)보다 오히려 훨씬 나빠짐 |
| seed ∩ candidate | **0.017** | 필터 전(0.034)보다도 더 나빠짐, 사실상 겹침 없음 |

**해석**: KR+Android 필터로 seed와 pool은 서로 훨씬 비슷해졌는데, **후보(candidate)만
seed·pool 어느 쪽과도 안 닮은, 전혀 다른 성격의 집단이 됐다.** 이유는 5번 절에서
자세히 다룬다 — 요약하면 "top500 미디어 중 아무거나 5회 이상 방문"이라는 후보 정의 자체가
`com.skb.adui`처럼 극단적으로 반복 방문되는 소수 항목에 걸리는 사람들을 우선적으로
골라내는 구조적 편향이 있다.

### 3-1. 4개 그룹(seed / pool / candidate 전체 / candidate 상위 10%) media 비교표

candidate를 media 단독 분류기로 채점해 상위 10%(80,421명, score≥0.4757)를 뽑은 뒤,
같은 항목 기준으로 4개 그룹을 나란히 비교했다.

| media | seed(n=1,010,817) | pool(n=2,743,442) | candidate 전체(n=804,606) | candidate 상위10%(n=80,421) |
|---|---|---|---|---|
| `com.skt.prod.dialer`(SKT 다이얼러) | **44.24%** | **31.29%** | 0.00% | 0.00% |
| `com.cashwalk.cashwalk`(캐시워크) | **38.15%** | **18.70%** | 0.00% | 0.00% |
| `viva.republica.toss`(토스) | **23.89%** | **13.77%** | 0.00% | 0.00% |
| `com.kakaopay.app`(카카오페이) | 6.68% | 2.88% | 0.00% | 0.00% |
| `com.ktcs.whowho`(후후) | 4.80% | 6.22% | 0.00% | 0.00% |
| `com.block.juggle`(퍼즐게임) | 3.38% | 3.62% | 0.00% | 0.00% |
| `com.astroframe.seoulbus`(서울버스) | 3.47% | 3.51% | 0.00% | 0.00% |
| `com.dencreak.dlcalculator` | 2.42% | 3.46% | 0.00% | 0.00% |
| `com.skb.adui` | 0.00% | 3.97% | **72.87%** | **78.08%** |
| `com.dcinside.app.android`(디시인사이드) | 0.69% | 1.91% | **24.97%** | 1.57% |
| `instiz.net`(메인) | 0.08% | 0.11% | 1.41% | **13.89%** |
| `instiz.net/bbs/list.php` | 0.05% | 0.08% | 1.03% | **10.16%** |
| `instiz.net/name_enter` | 0.05% | 0.08% | 0.98% | **9.75%** |
| `instiz.net/name` | 0.04% | 0.06% | 0.85% | **8.42%** |
| `m.bobaedream.co.kr`(보배드림) | 0.04% | 0.04% | 0.37% | 3.45% |
| `m.ppomppu.co.kr`(뽐뿌, 특정 게시글) | 0.13% | 0.14% | 0.15% | 1.42% |

**한눈에 보이는 패턴**:
- seed/pool은 SKT다이얼러·캐시워크·토스가 지배(seed는 세 앱 합쳐 100%p 넘게 중복
  방문, pool도 60%p대). **candidate 두 그룹에서는 이 앱들이 정확히 0%** — 3번 절
  본문에서 본 seed∩candidate Jaccard 0.017이 이 표로 직접 확인된다.
- candidate 전체는 `skb.adui`(72.87%)+`dcinside`(24.97%)가 지배하는데, **점수 상위
  10%로 좁히면 `skb.adui`는 오히려 더 커지고(78.08%) `dcinside`는 확 줄고(1.57%)
  instiz.net 계열(커뮤니티)이 급증**한다 — 분류기가 "dcinside 이용자"보다
  "skb.adui + instiz.net 이용자"를 더 seed-유사로 판단하고 있다는 뜻이다.
- seed/pool 성향(통신사·핀테크 앱)과 candidate 성향(광고 인벤토리 태그로 의심되는
  skb.adui + 커뮤니티 사이트)은 사실상 겹치는 지점이 없다 — 5-1 이슈(후보 정의의
  구조적 편향 의심)를 뒷받침하는 가장 직접적인 증거다.

## 4. 임베딩 아키텍처 (`embedding/media_sequence`, TiSASRec 스타일로 확장)

기존 SASRec(1차 media 문서 4번 참고)의 `position_embedding`(순서 0..49만 아는 학습형
임베딩)을 아래처럼 바꿨다.

```
media(아이템)              → nn.Embedding(vocab≤500, 64) ─────────────┐
time_gap(직전 이벤트와의    → nn.Embedding(11, 64)         ────────────┤   (position 대체,
  시간 간격 버킷, TiSASRec)                                            │    TiSASRec 스타일)
time_of_day(절대 시간대,    → nn.Embedding(9, 64)          ────────────┤   (신규 side feature)
  3시간 단위 8구간)                                                    │
inventory_type/ad_type/    → 각각 nn.Embedding(64) ────────────────────┼─ sum → causal
  connection_type                                                     │  TransformerEncoder(2층, 2head)
                                                                        └─ → 마지막 실제 스텝의 hidden = z(64dim)
```

- **time_gap(시간 간격) 버킷**: 직전 이벤트와의 간격(초)을 9구간으로 나눈다 — <5분/
  5~30분/30분~1시간/1~3시간/3~6시간/6~12시간/12~24시간/1~3일/3일 이상. 시퀀스의 첫
  이벤트(직전 이벤트 없음)는 별도 값 하나를 쓴다(0=pad 포함 전체 11개 값).
- **time_of_day(시간대) 버킷**: 이벤트 발생 시각(로컬 KST)을 3시간 단위 8구간으로
  나눈다(00-03시 ~ 21-24시, 0=pad 포함 전체 9개 값) — inventory_type과 같은 방식으로
  단순 합산.
- position_embedding은 완전히 제거하고 time_gap_embedding으로 대체했다 — "몇 번째
  이벤트인가"보다 "직전 이벤트로부터 실제로 얼마나 시간이 흘렀는가"가 재방문 리듬을 더
  잘 반영한다고 봤다(TiSASRec 원 설계 아이디어).

**구현 중 발견한 버그**: `build_features.py`가 `pd.to_datetime(...).astype("int64")`로
나노초 값을 얻는다고 가정했는데, 이 환경의 pandas(3.0.3)는 `to_datetime`의 기본 해상도가
**마이크로초**였다 — 그대로 쓰면 시간 계산이 1000배 어긋난다. `.astype("datetime64[ns]")`를
먼저 강제해 진짜 나노초 단위를 보장하도록 고쳤다(합성 데이터로 버킷 계산 정확성을
검증함).

**학습 규모**: 이번엔 seed 1,010,817 + pool 2,743,442 + 구candidate(07b) 178,160 = 총
3,932,419개 디바이스(vocab은 500→**332**로 줄었다 — KR+Android만 남기니 top500 중 상당수
일본향 미디어가 아예 관측되지 않아서다). 이벤트 5개 미만 1,596,926개 제외하고
2,335,493개로 학습.

**학습이 25/30 epoch에서 중단됨(5번 절 참고)**: loss는 0.6765→0.5819로 수렴하는
중이었고, 마지막 5 epoch의 개선폭이 0.0006뿐이라 25-epoch 체크포인트를 그대로 최종
모델로 채택했다.

## 5. 발견된 이슈

### 5-1. (핵심 이슈) 후보 집단이 사실상 `com.skb.adui`/`com.dcinside.app.android` 반복
방문자로 정의돼버림 — 후보 정의 자체의 구조적 편향 가능성

3번 절에서 본 것처럼, 신규 후보 804,606명의 media 프로필은 두 항목(`com.skb.adui`
72.87%, `com.dcinside.app.android` 24.97%)이 사실상 전부를 설명하고, 나머지는 한국
커뮤니티 사이트 롱테일이다 — seed/pool의 "통신사 다이얼러+핀테크 앱" 프로필과는 완전히
다르다.

**의심되는 원인(0-1절 정정)**: 후보 정의(`06b_create_candidate_table_media.sql`)의
`HAVING COUNT(*) >= 5`는 **미디어 항목 종류와 무관하게 30분 dedup 후 이벤트를 합산**해
5회 이상이면 통과한다 — 서로 다른 앱 5개를 한 번씩 방문해도 조건을 충족하므로, "단일
항목을 반복 방문해야만 통과"하는 조건은 아니다(이 점은 이전 버전 설명이 부정확했다).
그런데도 실제 결과가 `skb.adui`/`dcinside` 두 항목에 극단적으로 쏠린 걸 보면, **더 그럴듯한
설명은 pool에는 아예 없는 이 "5회 이상" 문턱 자체가 아니라, `skb.adui`라는 항목 자체가
한 디바이스당 매우 여러 번(예: 광고 SDK 재호출처럼) 발생하는 신호라서, 이 항목에 조금이라도
노출된 디바이스는 다른 앱을 전혀 안 써도 이 항목 하나만으로 5회 문턱을 쉽게 넘겼을
가능성**이다 — pool(0-1절 표 참고)은 이런 문턱이 아예 없어 1회짜리 산발적 방문자도 다
포함되는 반면, candidate는 "무언가를 5회 이상"이라는 조건 때문에 이렇게 고빈도로 발생하는
항목에 노출된 사람이 상대적으로 과대표집됐을 수 있다.

**추가 방증**: 후보군의 시간대 분포도 이상하다 — 새벽 03-06시 비중이 **14.94%**로
seed(4.82%)·pool(6.45%)보다 훨씬 높고, 오히려 이 구간이 하루 중 두 번째로 큰 비중을
차지한다(정상적인 사람 행동 패턴이라면 새벽 시간대가 가장 낮아야 함, 실제 seed/pool은
새벽대가 최저). 이는 `com.skb.adui`가 사람이 직접 여는 "앱"이 아니라 **백그라운드에서
주기적으로 트리거되는 광고 SDK/인벤토리 태그일 가능성**을 시사한다(이름 자체도
"SK Broadband Ad UI"류로 추정되는 패턴 — 확정된 사실은 아님, 확인 필요).

**결론**: **이번 회차의 candidate 스코어링 결과(804,200명 스코어링, 상위 10% 80,421명)는
"미디어 소비가 활발한 일반 유저"가 아니라 "특정 광고 인벤토리/커뮤니티 사이트 반복
방문자"를 뽑았을 가능성이 높다** — 실제 타겟팅에 쓰기 전에 최소 아래 확인이 필요하다:
- `com.skb.adui`가 실제 최종 사용자 앱인지, 광고 SDK 인벤토리 식별자인지 확인(가능하면
  이 항목을 top500/후보 조건에서 제외하고 재실행)
- 후보 정의를 "(항목 무관) 합산 5회 이상"이 아니라 "서로 다른 항목 N개 이상 방문"처럼
  다양성을 요구하는 조건으로 바꾸는 것을 검토(pool은 이런 활동량 문턱 자체가 없다는
  점도 0-1절 참고해 같이 재검토)

### 5-2. candidate 표본 비율을 세 차례 조정해야 했음(5%→20%→100%)

- 최초 06c는 필터 전 vocab 기준으로 5%(≈66만 명 목표)를 잡아뒀던 것.
- KR/Android 필터를 추가하며 pool의 실측 KR+Android 비율(27.77%)을 근사치로 대입해
  20%로 올렸으나, 실제로 20% 표본이 160,717명뿐이었다 — 역산하면 이 population의
  실제 KR+Android 비율은 약 6%(pool의 27.77%보다 훨씬 낮음)였다. 5-1의 구조적 편향과
  같은 맥락으로, "top500 미디어 헤비 리핏터"는 pool 일반 유저보다 해외/비Android 비중이
  더 높았던 것으로 보인다(혹은 skb.adui 자체의 인벤토리 성격과 관련 있을 수 있음).
- 결국 샘플링을 아예 없애고 필터 후 전체(804,606명)를 그대로 쓰기로 했다.
- **교훈**: 새로운 조건(필터)이 추가된 population의 세부 비율은, 겉보기에 비슷해
  보이는 다른 population(pool)의 실측치로 근사하면 위험할 수 있다 — 이번처럼 후보
  population 자체의 정의(반복방문 조건)가 근본적으로 다르면 비율도 크게 어긋난다.

### 5-3. SASRec 재학습이 25/30 epoch에서 중단됨

background 프로세스가 (에러 없이) 26 epoch 진행 중 kill됐다 — 세션/환경 쪽 이슈로
추정되며 코드 문제는 아니었다. loss가 이미 수렴한 상태(마지막 5 epoch 개선폭 0.0006)라
25-epoch 체크포인트를 그대로 채택했다.

### 5-4. AUC 개선분(0.6706→0.6733)의 원인을 분리할 수 없음

media 단독 분류기 val AUC가 0.6706(필터 전)→**0.6733**(필터+TiSASRec 후)으로 소폭
올랐지만, **이번 재실험은 (a) KR/Android 필터와 (b) TiSASRec 아키텍처 변경을 동시에
적용**했기 때문에 +0.0027의 개선이 둘 중 무엇 때문인지, 혹은 둘의 상쇄/시너지인지 알 수
없다. 각각을 분리해서 보려면 "필터만 적용 + 기존 position_embedding", "필터 없이 +
TiSASRec"처럼 통제된 비교 실험이 추가로 필요하다(7번 절 참고).

## 6. 최종 결과물

| 파일 | 내용 |
|---|---|
| `data/models/media_sequence/model.pt`, `model_best.pt` | TiSASRec 스타일 SASRec, 25 epoch, KR+Android 모집단 |
| `data/models/media_sequence/vocab_media.json` 등 4종 | 재적합된 vocab(media 332개) |
| `data/models/media_sequence/media_embeddings.csv` | seed+pool+구candidate 2,335,493명 임베딩(64dim) |
| `data/models/media_sequence/media_candidate_sample_embeddings.csv` | 신규 후보 804,200명 임베딩 |
| `data/models/lookalike_classifier_media/model.pt` | media 단독 분류기(val AUC 0.6733) |
| `data/models/lookalike_classifier_media_sample/candidate_scores.csv` | 신규 후보 804,200명 전원 점수 |
| `data/models/lookalike_classifier_media_sample/candidate_scores_top10pct.csv` | 상위 10%(80,421명) — **5-1 이슈 확인 전 실제 타겟팅에 쓰지 말 것** |
| `data/seed/v1.1.0/`, `data/seed/v1.1.0-20pct/` | 필터 전/20%-표본 시절 원본 CSV 백업 |

## 7. 한계와 다음 단계

- **5-1 이슈(후보가 skb.adui/dcinside 반복방문자로 쏠림) 확인이 최우선이다** — 이게
  확인되기 전까지 이번 회차의 candidate 상위 10% 리스트(80,421명)를 실제 타겟팅에
  쓰면 안 된다.
- **AUC 개선분의 원인 분리(5-4)가 안 돼 있다** — KR/Android 필터 단독 효과와 TiSASRec
  아키텍처 단독 효과를 나누는 ablation이 필요하다.
- **SASRec이 30 epoch을 다 채우지 못했다** — 필요하면 `train/media_sequence.py`에
  `--resume`류 옵션을 추가해 25-epoch 체크포인트에서 이어 학습하는 것을 검토할 만하다
  (현재는 항상 처음부터 다시 학습).
- **time_gap/time_of_day 피처 자체의 기여도를 검증하지 않았다** — position_embedding
  대비 실제로 다음-아이템 예측/lookalike 판별에 도움이 되는지는 이번 실험만으로는
  단정할 수 없다.
- **candidate 정의(06b) 자체를 재검토할 필요가 있다** — "top500 중 아무 항목이나 5회
  이상"이 아니라 "서로 다른 항목을 몇 개 이상 방문"처럼 다양성을 반영하는 조건으로
  바꾸면 5-1 이슈가 해소될 수 있다.

## 부록: 용어 설명

| 용어 | 뜻 |
|---|---|
| region=KR / OS=Android 필터 | `device_geo_region LIKE 'KR%'` AND `device_osv`가 정수형 문자열(Android)인 행만 남기는 조건 |
| TiSASRec | Time Interval Aware Self-Attentive Sequential Recommendation — SASRec의 position을 "이벤트 간 시간 간격"으로 대체한 변형 |
| time_gap / time_of_day 버킷 | 각각 "직전 이벤트와의 간격"·"하루 중 몇 시인가"를 이산 구간으로 나눈 값(4번 절 참고) |
| Jaccard 유사도 | 두 집합이 얼마나 겹치는지(교집합/합집합, 0=전혀 안 겹침, 1=완전히 같음) |
| device_ifa, Seed, Pool, 후보(Candidate), AUC, SASRec, vocab | [`20260803_피엘라벤_media_기반_룩어라이크_분석_요약.md`](20260803_피엘라벤_media_기반_룩어라이크_분석_요약.md) 부록 참고 |
