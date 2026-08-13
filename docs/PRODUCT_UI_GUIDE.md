# Swing Lab Product & UI Guide

> 상태: 공식 제품/UI 원칙  
> 기준일: 2026-08-13

## 1. 제품 성격

Swing Lab은 전통적인 증권사 HTS처럼 정보를 최대한 많이 쌓는 화면이 아니다.

목표 무드:

- 젊은 독립 금융앱
- 단순하지만 가독성이 높음
- 전문적인 금융정보이되 과하게 딱딱하지 않음
- 필요한 곳에만 이모지 사용
- 시선을 뺏는 장식보다 **지금 무엇을 판단해야 하는지**가 우선

## 2. 정보 우선순위

첫 화면에서 사용자가 빠르게 봐야 하는 순서:

1. 시장 상태
2. 지금 엄선된 후보
3. 후보의 현재 상태/진입가능성
4. BUY/TARGET/STOP
5. RSI / 120일선 / 볼린저 / 목표기간
6. 왜 선택됐는지
7. 장중 포착·이탈 변화
8. 마감 확정 추천 기록

백테스트는 후보 카드보다 아래 계층이다. **오늘의 매수 결정을 지배하는 합격/탈락 숫자로 보이게 하지 않는다.**

## 3. 타이포그래피

### Main headline

- `Black Han Sans`
- fallback: Pretendard / Noto Sans KR / sans-serif
- 큰 제목에만 제한적으로 사용
- 본문 전체에 사용하지 않는다.

### Body

- 시스템 산세리프 또는 Pretendard/Noto Sans 계열
- 숫자와 작은 설명은 최대한 읽기 쉽게
- 과도한 굵기 남용 금지

## 4. 핵심 색상

의미색은 임의로 여러 shade로 분산하지 않는다.

### 상승 / 목표 / 긍정

`#ff7d88`

사용:

- TARGET
- positive return
- success
- 상승 수익률

### 하락 / 손절 / 이탈 / 부정

`#76a1ff`

사용:

- STOP
- negative return
- exit
- 손절

### 진입 상태

검정/near-black 배경 + 흰 텍스트.

진입구간을 지나치게 pop한 starburst, lime sticker 등으로 강조하지 않는다.

### 중립

- off-white page
- white card
- neutral gray
- near-black text

## 5. 배지 원칙

### 포착

- `👀 포착`
- 회색 배지
- 장중 변화 중 “새로 들어온 후보”라는 의미만 전달
- 너무 경고처럼 보이지 않음

### 이탈

- 배경 `#76a1ff`
- 텍스트 white
- 이탈 이유는 아래에 별도 설명

### 진입구간

- compact black pill
- 카드 내부 flow에서 표시
- 카드 테두리 밖으로 돌출시키지 않는다.

## 6. 이모지 원칙

이모지는 정보 계층을 빠르게 읽는 보조수단으로만 쓴다.

현재 허용 예:

- `👌 지금 볼 만한 자리`
- `👀 포착`
- `🧪 가상계좌`
- `🧭` 상세 해석
- `💸` 투자금 계산

금지:

- 모든 카드에 이모지
- 모든 섹션 제목에 이모지
- 같은 의미의 이모지 여러 개
- 금융정보보다 이모지가 더 눈에 띄는 구성

## 7. LIVE 안내

LIVE 안내는 경고 ticker가 아니라 **조용한 상태 설명**이어야 한다.

현재 방향:

- 정적 배너
- 중립 회색 배경
- scroll/marquee 없음
- pop color 없음
- 문장 반복 없음

설명 목적:

- 형성 중 일봉에서는 후보가 들어왔다 빠질 수 있음
- 포착/이탈은 기록됨
- 공식 추천은 미국장 마감 후 확정됨

시장 전광판 같은 연출은 사용하지 않는다.

## 8. 추천 카드

카드의 주인공:

- 종목명 / ticker
- 현재 lifecycle 상태
- 현재가
- BUY
- TARGET
- STOP
- 핵심 지표
- 전략 이유

금지:

- 과도한 그림자
- 여러 색 배경
- 너무 많은 badge
- 성능 숫자를 광고처럼 강조

카드는 flat하고 정보 덩어리가 명확해야 한다.

## 9. 카드 상태

상태는 색뿐 아니라 텍스트로도 구분한다.

- 신규/추천 상태
- 진입 상태
- 현재 수익률
- 성공
- 손절
- 목표미달

색각 차이를 고려해 텍스트 label을 항상 유지한다.

## 10. 상세페이지

상세페이지는 “왜 이 종목인가?”를 설명하는 분석 sheet다.

우선순위:

1. 종목명 / ticker / 전략
2. 현재 score
3. 추천 이유
4. BUY / TARGET / STOP
5. 상세 차트
6. RSI / 추세 / 볼린저 / 수급 설명
7. Backtest
8. 투자금 계산
9. Paper action

score는 성공확률로 보이지 않게 설명한다.

## 11. 상세 차트

현재 차트 표현 규칙:

- 종가: near-black
- 120일선: blue family (`#76a1ff` semantic override 가능)
- 볼린저 상/하단: neutral gray
- BUY zone: neutral/light zone
- TARGET: `#ff7d88` dashed guide
- STOP: `#76a1ff` dashed guide
- TARGET/STOP 점선은 **가격 plot 전체 폭에 표시**
- 현재가 NOW는 가격 label만 유지하고 별도 점선은 표시하지 않아도 됨
- RSI는 보조영역으로 분리

차트는 전문 차트 플랫폼을 흉내내는 것이 아니라 진입/목표/손절 구조를 한눈에 보는 용도다.

## 12. 장중 포착 · 이탈

헤더 예:

- `장중 포착 · 이탈`
- meta: `현재 엄선 N개 · 이탈 이유까지 기록`

각 event:

- badge
- 종목명 / ticker
- 전략명
- 당시 엄선점수
- timestamp
- EXIT이면 구체적 이탈 이유

이 영역은 알림 feed 느낌은 줄 수 있지만 과한 색/모션은 금지한다.

## 13. 마감 확정 추천 기록

장중 feed와 시각적으로 구분한다.

목적:

- 공식 성과의 source
- 추천 당시 plan 보존
- SUCCESS/STOP/EXPIRED 확인

“오늘 지금 볼 후보”보다 시각 우선순위가 낮다.

## 14. Backtest UI

한 기간의 결과는 metric card/grid로 분리한다.

필수:

- total return
- win rate
- trades
- average trade
- Profit Factor
- MDD

함께 표시:

- buy & hold 비교
- cost drag
- 검증 데이터 부족 경고

숫자를 붙여서 한 줄로 보여주지 않는다.

## 15. Paper UI

Paper는 실주문과 혼동되면 안 된다.

- `🧪 가상계좌`
- Paper mode임을 명시
- 현금/평가금/예약현금 구분
- pending/open/closed 상태 표시
- 실계좌 주문 버튼처럼 보이는 과도한 긴장감을 피한다.

## 16. Motion

허용:

- 작은 hover
- overlay transition
- 간단한 feedback

비권장:

- 지속 marquee
- 무한 ticker
- 숫자 흔들림
- 화면 전체 animation
- 중요한 금융정보가 계속 이동하는 UI

`prefers-reduced-motion`을 존중한다.

## 17. MutationObserver 사용 규칙

UI가 동적으로 생성되기 때문에 observer를 쓸 수 있지만 반드시 scope한다.

- 추천 카드 → `#todayGrid`
- history → `#historyDays`
- chart → `#bigChart`

`document.body` 전체를 감시하며 텍스트를 재작성하는 구조는 금지에 가깝다.

observer callback은 idempotent해야 한다.

## 18. Mobile

모바일에서도 핵심 기능이 사라지면 안 된다.

- 카드 1열 우선
- metric grid는 2열 가능
- 긴 가격은 wrap
- overlay는 viewport 기준
- tap target 충분히 확보
- hover에만 의존하지 않음
- chart는 horizontal overflow 대신 viewBox scaling 우선

## 19. 접근성

- 상승/하락을 색만으로 전달하지 않음
- icon button에는 aria-label
- focus-visible outline 유지
- 작은 gray text는 대비를 너무 낮추지 않음
- 표/차트의 의미는 주변 텍스트에서도 이해 가능해야 함

## 20. 새 UI 변경 체크리스트

- [ ] 정보 우선순위가 좋아졌는가
- [ ] 장식 때문에 BUY/TARGET/STOP이 묻히지 않는가
- [ ] 의미색 `#ff7d88 / #76a1ff`가 유지되는가
- [ ] 이모지가 필요한 곳에만 있는가
- [ ] mobile에서 깨지지 않는가
- [ ] observer loop 위험이 없는가
- [ ] JS syntax check 추가했는가
- [ ] asset cache version이 필요한가
- [ ] 기존 detail/Paper/backtest 기능이 살아있는가

## 21. 디자인 변경 기록

브랜드 레벨 또는 semantic rule 변경은 `DECISION_LOG.md`에 남긴다.

예:

- headline font 변경
- semantic color 변경
- 진입 상태 표현 변경
- chart guide rule 변경
- motion 정책 변경
