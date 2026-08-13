# Swing Lab Decision Log

> 상태: 공식 주요 의사결정 기록  
> 작성 시작: 2026-08-13  
> 원칙: 전략/안전/성과측정/운영 구조처럼 나중에 “왜 이렇게 했지?”가 생길 만한 결정만 기록한다.

## 기록 형식

각 결정은 다음을 남긴다.

- 날짜
- 결정
- 이유
- 영향
- 재검토 조건

---

## 2026-08-13 · 공개 전략을 3개로 유지

**결정**

메인 공개 전략은 아래 3개로 유지한다.

- 확인형 눌림반등
- RSI2 추세내 과매도
- 모멘텀 눌림 지속

변동성 수축 돌파는 실험/검증 전략으로 남긴다.

**이유**

메인 후보 화면의 목적은 검증이 충분하지 않은 전략을 많이 보여주는 것이 아니라, 현재 정의가 명확한 전략을 일관되게 검증하는 것이다.

**재검토 조건**

실험 전략이 `VALIDATION_PROTOCOL.md`의 OOS/독립감사/비용 적용 조건을 통과할 때.

---

## 2026-08-13 · strict signal과 BUY/TARGET/STOP을 canonical source로 통합

**결정**

`strategy_rules.py`를 live/backtest가 공동 사용하는 단일 원본으로 둔다.

**이유**

과거에는 live scanner와 backtest의 조건이 일부 달라 결과를 직접 비교하기 어려웠다. 전략 연구에서 가장 먼저 필요한 것은 “같은 전략을 테스트하고 있는가”라는 parity다.

**영향**

전략 조건 변경 시 live와 backtest가 동시에 바뀐다. 임계값 변경은 반드시 validation protocol을 따른다.

---

## 2026-08-13 · minimum stop margin을 1.5 ATR로 통일

**결정**

최종 STOP은 entry에서 최소 1.5 ATR 손절여유를 확보한다.

**이유**

기술적 low만 그대로 사용하면 지나치게 촘촘한 stop이 만들어질 수 있고, 전략 간 risk model이 달라질 수 있다.

**재검토 조건**

pooled OOS 연구에서 다른 ATR margin이 명확하게 우월할 때.

---

## 2026-08-13 · raw 전략 S와 최종 엄선을 분리

**결정**

전략별 S 신호와 메인 “엄선” 후보는 동일하지 않다.

**이유**

좋은 전략 신호가 발생해도 현재 가격이 이미 추격구간이거나, 손익비/수급/시장상태가 나쁠 수 있다. 전략 자체의 신호 품질과 “지금 진입할 자리인가”를 분리해야 한다.

**현재 엄선 hard gate**

- RR >= 1.20
- flow >= 42
- 시장 `조심` 제외
- entry viable
- stop margin >= 1.5 ATR
- elite score >= 72

---

## 2026-08-13 · Backtest는 오늘 추천 hard gate로 사용하지 않음

**결정**

개별 종목의 10년 backtest 결과가 좋거나 나쁘다는 이유로 오늘 후보를 자동 합격/탈락시키지 않는다.

**이유**

개별 종목은 거래 표본이 작고 survivorship/regime 영향이 크다. 전략의 장기 검증과 오늘의 현재 setup quality는 다른 문제다.

**영향**

Backtest는 상세페이지의 참고자료이며 전략 전체 연구는 pooled OOS로 수행한다.

---

## 2026-08-13 · Backtest V2를 보수적 체결 모델로 사용

**결정**

- 양방향 commission
- slippage
- half spread
- gap stop 불리 체결
- gap target 보수 처리
- same-bar stop first
- finite capital

을 기본으로 사용한다.

**이유**

이상적 체결을 가정한 높은 수익률보다 실제로 견딜 수 있는 모델이 중요하다.

---

## 2026-08-13 · 독립 실행엔진으로 Backtrader 추가

**결정**

Swing Lab 자체 execution 외에 Backtrader native broker로 독립 감사를 수행한다.

**이유**

자체 backtest 코드의 오류를 자체 코드만으로 검증하는 한계를 줄이기 위해서다.

**영향**

canonical signal/plan만 공유하고 체결 구현은 분리한다. 차이가 발생하면 숨기지 않고 원인을 분류한다.

---

## 2026-08-13 · 기본 계좌 모델 300만원 / 최대 3포지션

**결정**

검증 기본값:

- 3,000,000 KRW
- max 3 positions
- risk 1% / trade
- max 40% / position

**이유**

무한자본 개별 종목 백테스트보다 실제 계좌에서 동시에 몇 개를 살 수 있는지가 중요하기 때문이다.

**재검토 조건**

사용 목적 자체가 바뀌거나 별도 계좌 profile 기능이 생길 때.

---

## 2026-08-13 · 장중 후보와 공식 추천을 분리

**결정**

추천 데이터를 3단계로 나눈다.

1. 실시간 후보
2. 장중 포착·이탈
3. 마감 확정 추천

**이유**

형성 중 일봉은 RSI/볼린저/현재가/거래량이 계속 변한다. 장중 잠깐 들어온 후보를 공식 추천 성과에 넣으면 look/record convention이 불안정해진다.

**영향**

공식 성과는 마감 확정 추천만 사용한다.

---

## 2026-08-13 · 공식 추천은 미국 동부 16:05 이후 동결

**결정**

`journal.py`는 ET 16:05 이후 스캔만 `CONFIRMED_CLOSE`로 publish한다.

**이유**

미국 일봉이 충분히 마감된 이후에 추천 상태를 고정하기 위해 buffer를 둔다.

**영향**

결과 판정은 다음 거래일부터 시작한다.

---

## 2026-08-13 · 장중 EXIT 이유를 구조화해 저장

**결정**

단순 “이탈”이 아니라 실제 실패 조건을 기록한다.

**가능 code**

- signal_missing
- strategy_score
- flow
- risk_reward
- market
- entry_viable
- atr_stop_margin
- elite_score
- elite_rules

**이유**

나중에 후보가 왜 사라졌는지 설명할 수 있어야 strategy/filter 연구에도 쓸 수 있다.

**원칙**

과거 구버전 로그에 데이터가 없으면 이유를 소급해서 지어내지 않는다.

---

## 2026-08-13 · Paper Broker를 실주문 이전 필수 계층으로 둠

**결정**

실제 brokerage adapter 전에 Paper Broker를 통과해야 한다.

**이유**

백테스트는 주문 상태, 현금 예약, 정수 수량, 실제 환율, 다음날 open 취소 같은 실운영 문제를 충분히 검증하지 못한다.

**안전 경계**

현재 live trading disabled. 실제 주문 전송 기능 없음.

---

## 2026-08-13 · Browser별 Paper 상태 + local backup recovery

**결정**

browser client ID로 Paper state를 분리하고 localStorage backup을 Render 재배포 후 recovery 용도로 사용한다.

**이유**

Render의 ephemeral server state가 재배포 시 초기화될 수 있기 때문이다.

**제약**

계정 기반 multi-device persistence가 아니다. stale backup이 active server state를 덮어쓰지 않게 한다.

---

## 2026-08-13 · Toss API는 후속 adapter 목표, 실주문은 별도 승인 단계

**결정**

향후 Toss Open API 연결 가능성은 연구하되, 현재 Swing Lab은 실주문을 활성화하지 않는다.

**순서**

1. Paper
2. read-only/account data
3. order payload validation
4. safety guard
5. 별도 승인 후 제한적 live 논의

**이유**

전략 검증과 brokerage execution safety는 서로 다른 승격 문제다.

---

## 2026-08-13 · 자동 스캔 데이터 커밋은 Render 재배포를 건너뜀

**결정**

scheduled data commit message에 `[skip render]`를 사용한다.

**이유**

30분 스캔마다 main이 바뀌면서 Render가 매번 재시작하면 서비스 안정성이 떨어진다.

**영향**

코드 변경은 배포되지만 JSON 데이터 refresh는 서버 재배포 없이 갱신된다.

---

## 2026-08-13 · first-load에서 외부 환율 network를 기다리지 않음

**결정**

persisted USD/KRW cache를 사용한다.

**이유**

첫 화면 API가 Yahoo Finance 환율 응답을 기다리면서 HTML shell만 뜨고 데이터가 무한 로딩되는 장애가 발생했다.

**영향**

첫 화면은 저장 환율을 즉시 사용하고 환율 갱신은 스캔 workflow에서 처리한다.

---

## 2026-08-13 · global MutationObserver를 피함

**결정**

동적 UI observer는 필요한 container로 scope한다.

**이유**

두 UI script가 동일 heading을 서로 다른 텍스트로 반복 수정하면서 body-wide observer loop가 발생해 브라우저 main thread가 잠긴 장애가 있었다.

**영향**

- `#todayGrid`
- `#historyDays`
- `#bigChart`

등 필요한 영역만 관찰하고 callback은 idempotent하게 작성한다.

---

## 2026-08-13 · UI semantic color 통일

**결정**

- 상승/목표/긍정: `#ff7d88`
- 하락/손절/이탈: `#76a1ff`

**이유**

기존 여러 red/blue shade가 혼재해 의미가 분산됐다.

**영향**

차트, 수익률, 목표/손절, outcome까지 같은 semantic palette를 사용한다.

---

## 2026-08-13 · LIVE ticker 제거

**결정**

움직이는 검정 ticker + pop color를 제거하고 정적인 neutral gray 안내로 변경한다.

**이유**

금융앱보다 시장 전광판처럼 보여 정보 집중을 방해했다.

**원칙**

지속적으로 움직이는 정보는 꼭 필요한 경우가 아니면 사용하지 않는다.

---

## 2026-08-13 · 진입구간 starburst sticker 제거

**결정**

팝그린 뾰족 starburst 대신 카드 flow 안의 compact black pill로 표시한다.

**이유**

진입구간 배지가 종목/가격 정보보다 너무 강하게 튀었다.

---

## 2026-08-13 · 상세차트 TARGET/STOP guide 전체 폭

**결정**

- TARGET dashed line → price plot 전체 폭
- STOP dashed line → price plot 전체 폭
- NOW current-price dashed line → 제거, label만 유지

**이유**

목표/손절 위치를 차트 전체 움직임과 비교하기 쉽게 하고 현재가 가이드선 중복을 줄인다.

---

## 2026-08-13 · 공식 문서 체계 도입

**결정**

프로젝트 지식은 다음 문서로 분리한다.

- `PROJECT_MASTER_PLAN.md`
- `TRADING_RULES.md`
- `VALIDATION_PROTOCOL.md`
- `SYSTEM_OPERATIONS.md`
- `PRODUCT_UI_GUIDE.md`
- `DECISION_LOG.md`

**이유**

README와 PR 설명, 코드에 지식이 흩어져 있고 일부 README 내용이 실제 production 상태보다 오래돼 있었다.

**향후 규칙**

전략/안전/운영/제품 원칙이 바뀌는 PR은 관련 공식 문서를 같은 PR에서 함께 수정한다.
