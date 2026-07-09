# querys/addi_conv/

`"prod_addi_conv".raw_conv_web` / `raw_conv_web_imp`(광고주 몰 방문 로그)를 이용해 "전환"을
"postback(광고 반응) 발생 여부"가 아니라 "postback 유저 중 실제 몰 IP와 매칭되는 유저 비율"로
재정의하는 트랙. 배경/의사결정 과정은 `docs/_archive/202607091533.md` 참고.

## 사용하는 쿼리 (현재 파이프라인)

| # | SQL | 역할 |
|---|---|---|
| 09 | `09_postback_conv_match_jun_for_backtest.sql` | 6월 postback 유저 전원의 IP(+cmp_no) 매칭 여부 — 백테스트 라벨 |
| 10 | `10_postback_users_profile_jun.sql` | 6월 postback 유저 전원의 프로필 (user_profile 추론 입력) |
| 11 | `11_postback_users_media_visit_jun.sql` | 6월 postback 유저 전원의 미디어 방문 (media_sequence 추론 입력) |

실행 방법/이후 단계(임베딩 추출→스코어링→백테스트)는 루트 [`README.md`](../../README.md)
"전환 정의 변경 백테스트" 절 참고.

## `_archived/` — 스키마/매칭 방식 진단 쿼리 (결론 남, 재실행 불필요)

`raw_conv_web(_imp)`를 한 번도 조회한 적이 없는 상태에서 스키마·매칭 신뢰도를 확인하기 위해
작성한 1회성 진단 쿼리들. 결론은 다음과 같이 위 09~11 쿼리와 `docs/_archive/202607091533.md`에
반영됐다:

- **00**(postback ip 품질), **08**(매칭 민감도): postback_log의 `ip`는 결측 0.001%, IPv4 포맷
  100%, `ip`≈`request_ip`(98.4% 일치), IP 하나당 distinct ifa 중앙값 1(공유 IP/NAT 위험 낮음).
  04~05월 postback 유저 564,492명 중 IP+cmp_no 매칭 412명(0.073%, 시간창 무관) — 절대 건수가
  매우 작다는 게 확인됨(→ 재학습 시 5% 샘플링 문제로 이어짐, 아래 참고).
- **01/02/03**(스키마/샘플): `raw_conv_web(_imp)` 컬럼은 `cmp_no, pid, ev, mall_dt,
  post_datetime, mall_datetime, mall_ip, cate` (+파티션). `post_datetime`은 `mall_datetime`과
  무관하게 튀는 값이라 신뢰 불가 판정, 매칭에는 `mall_datetime`만 사용.
- **04**: `raw_conv_web` 119,683행 / `raw_conv_web_imp` 47,648행, distinct mall_ip 각 31,776 /
  18,958.
- **05**(ev/cate 분포): ev는 99.95%가 `page_view`(몰 방문), `order`(실구매)는 전체 테이블
  합쳐 60건뿐 — "전환"을 order 단독으로 제한하면 매칭 후 양성이 0에 수렴해 학습/백테스트
  불가능. **사용자 확인 후 "몰 방문(전체 ev)"을 전환으로 채택.**
- **06**(pid↔cmp_no): cmp_no마다 distinct pid = 1 — `pid`는 유저 식별자가 아니라 캠페인당
  고정 픽셀/게시물 토큰. 유저 단위 조인 키는 `mall_ip`뿐임을 확정.
- **07**(cmp_no 도메인 겹침): postback 22개 cmp_no 중 13개가 conv_web의 14개 cmp_no와 겹침
  (93%) — `raw_conv_web.cmp_no`가 addi 캠페인 cmp_no와 같은 ID 체계임을 확인. 이후 매칭에
  `mall_ip` 단독 대신 `mall_ip + cmp_no`를 기본으로 채택(정밀도 향상).
