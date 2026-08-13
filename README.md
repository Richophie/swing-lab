# Swing Lab · 오늘의 스윙자리

개인용 미국주식 스윙 후보 탐색·검증 도구입니다.

## 현재 구조

운영 코드는 버전 파일을 연쇄 상속하지 않습니다.

- `app.py` — Flask API / 웹 진입점
- `market_data.py` — 가격 데이터, 지표, 미국 종목 universe, 시장 상태
- `strategy_rules.py` — 실전/백테스트가 공동 사용하는 엄격 신호와 BUY/TARGET/STOP 단일 원본
- `strategy_engine.py` — 전략 점수·설명·현재 매매계획; 엄격 신호와 가격 계획은 `strategy_rules.py` 사용
- `scanner.py` — 미국 종목 스캔과 추천 캐시 생성
- `journal.py` — 날짜별 추천 스냅샷과 결과 판정
- `backtest_engine.py` — canonical 규칙 + 현실적 체결비용/갭 규칙을 사용하는 Backtest V2
- `portfolio_backtest.py` — 여러 종목 신호를 하나의 300만원 계좌로 합성하는 동시보유/포지션 사이징 시뮬레이터
- `backtrader_audit.py` — 같은 canonical 신호/가격계획을 Backtrader의 독립 브로커에서 재체결해 결과 차이를 감사
- `audit_matrix.py` — 실제 10년 데이터 20종목 × 공개 3전략 교차 엔진 감사 리포트
- `walkforward.py` — OOS / Walk-forward 검증
- `stock_names.py` — 한글 종목명 단일 관리
- `qa.py` — 회귀/구조 검증 및 live/backtest 규칙 배선 검사
- `static/dashboard.html` — 단일 대시보드 UI

## 공개 전략

1. 확인형 눌림반등
2. RSI2 추세내 과매도
3. 모멘텀 눌림 지속

변동성 수축 돌파 전략은 메인 추천에서 숨기고 기록/검증 데이터로만 유지합니다.

## 검증 원칙

- 엄격 매수 신호는 `strategy_rules.py` 한 곳에서 정의합니다.
- BUY/TARGET/STOP과 최소 1.5 ATR 손절 여유도 같은 모듈을 실전과 백테스트가 함께 사용합니다.
- 백테스트의 과거 시장 상태는 현재 시장 필터와 같은 SPY/QQQ 120일선·200일선·RSI>45 점수 체계로 재구성합니다.
- 다음 거래일 시가가 실전 진입 허용 범위를 크게 벗어나면 백테스트에서도 체결하지 않습니다.
- 한 일봉에서 목표와 손절을 모두 터치한 경우 Swing V2는 보수적으로 손절을 먼저 적용합니다.

## Backtest V2 체결 모델

- 진입 시가에는 보수적인 반스프레드 + 슬리피지를 적용합니다.
- 손절가 아래로 갭다운하면 손절가 체결로 가정하지 않고 더 나쁜 시가에서 stop-market 체결비용을 적용합니다.
- 목표가 위로 갭업해도 미래의 유리한 가격을 과대평가하지 않도록 목표가 체결만 인정합니다.
- 수수료는 진입/청산 양쪽에 각각 적용합니다.
- 기본값은 수수료 편도 0.10%, 슬리피지 5bp, 반스프레드 2.5bp이며 `config.py`에서 한 번에 조정합니다.

## 300만원 계좌 시뮬레이터

- 기본 초기자금은 3,000,000원, 최대 동시보유 3종목입니다.
- 한 거래의 계획 손실을 계좌의 1% 이내로 맞추는 risk-based sizing을 우선 사용하고, 한 종목은 계좌의 40%를 넘지 않습니다.
- 같은 날 후보가 많으면 미래 수익률이 아니라 진입 당시 계산 가능한 canonical 손익비가 높은 순으로 선택합니다.
- 같은 날 청산되는 돈을 그날 시가 신규진입에 다시 쓰지 않아 체결 순서를 보수적으로 처리합니다.
- 포지션은 KRW 명목노출 기준의 fractional exposure로 계산합니다. 역사적 환율이나 주식 수량 반올림은 강제로 가정하지 않으며, 실제 주식 수량 계산은 향후 Paper Broker/Toss 주문 계층에서 처리합니다.

## Backtrader 독립 감사

Backtrader 감사 경로는 Swing Lab의 체결 함수를 호출하지 않습니다. canonical 신호와 BUY/TARGET/STOP만 입력으로 공유하고, 실제 주문 체결은 Backtrader native broker의 Market + Stop/Limit bracket, commission, slippage 모델에 맡깁니다.

실제 10년 데이터 기준 20종목 × 공개 3전략 = 60조합 감사 결과:

- 전체: PASS 30 / PASS_WITH_DIFFERENCES 22 / NO_TRADES 8 / REVIEW 0 / 실행 오류 0
- 확인형 눌림반등: Swing 48건 / Backtrader 48건, 진입일 일치 100.0%, 결과 일치 100.0%, 평균 절대 수익률 차이 0.418%p
- RSI2 추세내 과매도: Swing 232건 / Backtrader 226건, 진입일 일치 96.6%, 결과 일치 99.1%, 평균 절대 수익률 차이 0.267%p
- 모멘텀 눌림 지속: Swing 42건 / Backtrader 42건, 진입일 일치 100.0%, 결과 일치 100.0%, 평균 절대 수익률 차이 0.573%p

RSI2의 진입일 차이는 Swing-only 7건, Backtrader-only 1건입니다.

- MSFT: Swing-only 2022-01-07
- AMZN: Swing-only 2019-08-02, 2025-02-25 / Backtrader-only 2025-02-26
- CAT: Swing-only 2024-12-20
- QCOM: Swing-only 2019-12-04
- F: Swing-only 2026-08-07
- PLD: Swing-only 2026-08-05

결과 분류 차이는 NKE RSI2의 2건입니다.

- 2017-08-21 진입: Swing은 당일 손절(-2.291%), Backtrader는 기간종료(2017-08-29, -3.407%)
- 2021-12-20 진입: Swing은 당일 손절(-2.575%), Backtrader는 다음날 목표달성(2021-12-21, +5.621%)

두 NKE 사례는 신호 규칙 차이보다 일봉 내부 주문 순서 해상도 차이로 해석하는 것이 타당합니다. Swing V2는 다음날 시가 진입 직후 같은 일봉의 Stop/Target 터치를 즉시 평가하지만, Backtrader의 일봉 bracket은 부모 Market 진입이 체결된 뒤 같은 OHLC 봉 내부에서 자식 Stop/Limit 주문이 어떤 순서로 터졌는지 완전히 재구성할 수 없습니다. 이 차이는 숨기지 않고 감사 리포트에 남깁니다.

## 자동 실행

GitHub Actions의 `Market Scan Cache`가 장중 주기적으로:

1. 모듈 문법 검사
2. 최신 스캔 생성
3. QA 통과 여부 확인
4. 날짜별 추천 기록 및 결과 갱신
5. 캐시 파일 커밋

순서로 실행됩니다.

PR Core Validation은 canonical 전략 parity, Backtest V2 체결/계좌 테스트, Backtrader native broker 테스트, 실제 10년 × 20종목 × 3전략 감사 리포트를 실행하고 JSON artifact를 저장합니다.

Render는 `gunicorn app:app`으로 현재 `app.py`만 실행합니다.
