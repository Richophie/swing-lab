# Manual Paper vs Automatic Research Lab · 2026-08-13

> 상태: 공식 제품/운영 구조

## 목적

Swing Lab의 가상매매를 두 개의 완전히 다른 계좌로 분리한다.

### 1. 가상계좌 · 사용자 연습용

사용자가 직접 사고 싶은 종목을 선택한다.

- 실시간 후보 또는 `사라마라`에서 종목을 확인한다.
- 사용자가 수량을 직접 입력할 수 있다.
- 수량을 비우면 기존 엔진 리스크 규칙으로 자동 계산한다.
- 입력 수량은 엔진이 허용한 최대 수량을 초과할 수 없다.
- `PENDING` 주문은 사용자가 취소할 수 있다.
- `FILLED` 포지션은 사용자가 현재 시장가 가정으로 전량 가상매도할 수 있다.
- 후보가 실시간 화면에서 이탈해도 가상계좌 장부에는 주문/포지션이 남는다.
- 실제 brokerage 주문은 전송하지 않는다.

이 계좌의 목적은 **사용자의 매매 연습과 의사결정 기록**이다.

### 2. 자동거래연구소 · Shadow Portfolio

사람이 종목을 고르거나 중간에 매도하지 않는다.

- 입력 신호: 미국장 마감 후 동결된 `official_public` 추천만 사용
- 연구 시작일: 2026-08-13
- 초기자금: 3,000,000 KRW
- 최대 동시 포지션: 3
- 거래당 risk budget: equity의 1%
- 종목당 최대 노출: equity의 40%
- 같은 날 후보가 자리를 경쟁하면 ex-ante gross risk/reward 우선
- 다음 거래일 open이 BUY ± gap guard 안이면 가상 체결
- STOP / TARGET / 기간종료는 Paper Broker canonical execution 사용
- commission / slippage / half-spread 가정 유지
- event-risk snapshot을 주문 시점에 저장
- 사람의 수동매도/수동취소 없음
- 실제 brokerage 주문 기능 없음

이 계좌의 목적은 **백테스트가 아니라 실제 그날 공개된 추천의 forward 성과를 축적**하는 것이다.

## 왜 분리하는가

사용자 가상계좌에는 선택편향이 들어간다.

예를 들어 사용자가 마음에 드는 추천만 고르면 결과가 좋아도:

- 전략이 좋아서인지
- 사용자의 추가 판단이 좋아서인지

구분할 수 없다.

Shadow Portfolio는 공식 마감추천을 기계적으로 처리해 이 선택편향을 줄인다.

따라서 향후 전략 개선의 1차 forward evidence는 자동거래연구소를 사용하고, 사용자 가상계좌 성과는 별도 참고자료로 본다.

## 데이터 저장

자동거래연구소 장부:

`static/shadow_portfolio.json`

GitHub Market Scan workflow가:

1. live scan
2. intraday signal log
3. close-confirmed journal
4. Shadow Portfolio advance
5. JSON data commit `[skip render]`

순서로 갱신한다.

따라서 브라우저 localStorage나 Render ephemeral filesystem에 의존하지 않는다.

## 제품 탭

- `실시간후보` — 현재 스캔에서 잡힌 전략 S/엄선 후보
- `사라마라` — 사용자가 찍은 종목이 현재 공개 3전략에 얼마나 맞는지 검사
- `엔진` — 스캔/시장/규칙/로그/연구계좌 상태판
- `가상계좌` — 사용자가 직접 수량을 정하고 사고파는 연습계좌
- `자동거래연구소` — 마감 확정 추천을 자동 처리하는 forward research 계좌

## 장중 로그 정의 변경

장중 로그는 전략 S와 엄선을 분리한다.

- `S 포착` — strategy score가 S threshold를 통과
- `재포착` — 같은 장중에 S 이탈 후 다시 S 복귀
- `엄선 승격` — S는 이미 유지 중이며 elite gate까지 통과
- `엄선 해제` — S는 유지하지만 elite gate에서 빠짐
- `이탈` — 전략 S 자체가 사라짐

이렇게 해야 RR/수급 같은 elite 경계에서 흔들리는 종목을 `포착 ↔ 이탈`로 오해하지 않는다.

## 안전 경계

`live_trading_enabled = false`

가상계좌와 자동거래연구소 모두 실제 증권 주문을 전송하지 않는다.
향후 brokerage adapter가 생기더라도 Shadow Portfolio의 연구 장부와 실주문 계층은 별도 승인/검증 절차를 둔다.
