# Swing Lab · 오늘의 스윙자리

개인용 미국주식 스윙 후보 탐색·검증 도구입니다.

Swing Lab은 단순 스캐너가 아니라 **전략 신호 → 현재 자리 엄선 → 장중 포착/이탈 → 마감 확정 추천 → 결과 추적 → 백테스트/독립감사 → Paper Broker**까지 이어지는 검증 시스템을 목표로 합니다.

## 공식 문서

프로젝트의 목표와 규칙은 아래 문서를 기준으로 관리합니다.

| 문서 | 역할 |
|---|---|
| [`docs/PROJECT_MASTER_PLAN.md`](docs/PROJECT_MASTER_PLAN.md) | 전체 기획안, 목표, 범위, 현재 구조, 로드맵 |
| [`docs/TRADING_RULES.md`](docs/TRADING_RULES.md) | 공개 전략, BUY/TARGET/STOP, 엄선, 장중/마감 추천, 계좌 규칙 |
| [`docs/VALIDATION_PROTOCOL.md`](docs/VALIDATION_PROTOCOL.md) | 전략 연구, OOS/Walk-forward, Backtrader 감사, 승격/퇴출 원칙 |
| [`docs/SYSTEM_OPERATIONS.md`](docs/SYSTEM_OPERATIONS.md) | 자동 스캔, Render, 저장 데이터, Paper persistence, 장애 대응 |
| [`docs/PRODUCT_UI_GUIDE.md`](docs/PRODUCT_UI_GUIDE.md) | UI 정보 위계, 색상, 이모지, 카드/차트/모바일 원칙 |
| [`docs/DECISION_LOG.md`](docs/DECISION_LOG.md) | 중요한 설계/전략/운영 의사결정과 이유 |
| [`STRATEGY_LAB_PLAN.md`](STRATEGY_LAB_PLAN.md) | 초기 전략 연구 메모; 공식 연구 절차는 Validation Protocol 우선 |

전략/안전/운영/제품 원칙이 바뀌는 코드 변경은 관련 공식 문서를 같은 PR에서 함께 갱신하는 것을 원칙으로 합니다.

## 현재 공개 전략

1. `confirmed_pullback` — 확인형 눌림반등
2. `rsi2_trend_reversion` — RSI2 추세내 과매도
3. `momentum_pullback` — 모멘텀 눌림 지속

`volatility_breakout`은 실험/검증 전략으로 유지하며 메인 엄선에서는 제외합니다.

strict signal과 BUY/TARGET/STOP의 canonical source는 `strategy_rules.py`입니다.

## 추천의 세 단계

### 실시간 후보

형성 중인 미국 일봉을 사용하므로 RSI·볼린저·현재가·거래량 변화에 따라 목록이 바뀔 수 있습니다.

### 장중 포착 · 이탈

엄선 후보의 ENTER/EXIT transition을 `static/signal_events.json`에 남깁니다. EXIT에는 가능한 경우 수급, 손익비, 시장, 진입구간, ATR 손절여유 등 실제 이탈 이유를 함께 기록합니다.

### 마감 확정 추천

공식 성과 기록은 미국 동부시간 16:05 이후에 `journal.py`가 `CONFIRMED_CLOSE`로 동결한 추천만 사용합니다. 결과 판정은 다음 거래일부터 시작합니다.

## 현재 엄선 hard gate

전략 S 신호 중 현재 자리까지 다시 확인합니다.

- 손익비 `>= 1.20:1`
- 수급/유동성 점수 `>= 42`
- 시장 상태 `조심` 제외
- 현재 진입 가능
- 최소 `1.5 ATR` 손절여유
- 최종 엄선점수 `>= 72`

백테스트 결과는 오늘 후보의 합격/탈락 hard gate로 사용하지 않습니다.

## 기본 계좌 모델

- 초기자금: 3,000,000 KRW
- 최대 동시 포지션: 3
- 거래당 계획손실: 계좌의 1%
- 종목당 최대 노출: 계좌의 40%

Backtest portfolio는 KRW 명목노출로 비교하고, 실제 USD 환율/정수 수량/현금 흐름은 Paper Broker에서 검증합니다.

## 검증 구조

### Backtest V2

- 양방향 commission
- slippage
- half spread
- next-session open
- gap guard
- gap stop 보수 처리
- target gap 보수 처리
- same-bar stop-first
- finite capital

현재 기본 비용 가정:

- commission: 편도 0.10%
- slippage: 5 bps
- half spread: 2.5 bps

이 값은 특정 증권사의 현재 실제 수수료를 주장하는 값이 아니라 보수적 검증 가정입니다.

### Backtrader 독립 감사

canonical signal/price plan만 공유하고 주문 체결은 Backtrader native broker가 담당합니다. Swing Lab 자체 execution helper를 재사용하지 않아 독립적인 재현성 감사를 수행합니다.

### Paper Broker

실주문 권한이 전혀 없는 가상 주문 계층입니다.

- 정수 주식 수량
- 실제 USD/KRW
- pending cash reservation
- PENDING → FILLED → CLOSED/CANCELLED
- next-session open only
- gap reject
- commission/slippage/spread
- same-bar stop-first
- realized/unrealized P&L
- browser별 Paper client
- localStorage recovery backup

`live_trading_enabled`는 false로 유지하며 실제 brokerage order-send 기능은 없습니다.

## 주요 파일

- `app.py` — Flask API/웹 기능
- `paper_entry.py` — production Flask entry + Paper restore route
- `market_data.py` — 가격/지표/universe/시장상태
- `strategy_rules.py` — canonical strict signal + trade levels
- `strategy_engine.py` — 전략 점수/설명
- `scanner.py` — 스캔 + 최종 엄선
- `signal_log.py` — 장중 ENTER/EXIT
- `journal.py` — 마감 확정 추천 + 결과
- `backtest_engine.py` — Backtest V2
- `portfolio_backtest.py` — finite-capital simulation
- `backtrader_audit.py` — independent broker audit
- `audit_matrix.py` — real-data audit matrix
- `paper_broker.py` — Paper lifecycle engine
- `paper_broker_service.py` — Paper service/CLI
- `paper_restore.py` — browser backup recovery
- `walkforward.py` — OOS/Walk-forward research
- `static/` — dashboard assets + saved scan/history data

## Production

Render 설정은 `render.yaml`을 기준으로 합니다.

```bash
gunicorn paper_entry:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180
```

코드가 `main`에 merge되면 Render automatic deploy가 실행됩니다.

30분 자동 스캔이 생성하는 data-only commit은 `[skip render]`를 포함해 불필요한 Render 재배포를 막습니다.

## 자동 스캔

`.github/workflows/market-scan.yml`이 장중 주기적으로 실행합니다.

1. compile
2. latest scan 생성
3. USD/KRW persisted cache 갱신
4. 장중 ENTER/EXIT 기록
5. QA
6. 마감 확정 추천/결과 업데이트
7. JSON data commit `[skip render]`

저장 데이터:

- `static/latest_scan.json`
- `static/fx_cache.json`
- `static/signal_events.json`
- `static/trade_history.json`

## PR 검증

`.github/workflows/pr-core-validation.yml`은 주요 변경에서 다음을 검증합니다.

- Python compile
- JavaScript syntax
- canonical strategy parity
- Backtest V2
- Backtrader independent tests
- Paper Broker lifecycle
- Paper restore
- signal history/publication
- startup/deploy stability
- detail/backtest/Paper UI regression
- real 10y × 20 stocks × 3 strategies audit

## 로컬 실행

```bash
pip install -r requirements.txt
python app.py
```

배포와 동일한 Paper restore route까지 포함해 테스트하려면 gunicorn/Flask entry를 `paper_entry:app` 기준으로 확인합니다.

Paper CLI 예:

```bash
python paper_broker_service.py status
python paper_broker_service.py submit SIRI --strategy rsi2_trend_reversion
python paper_broker_service.py refresh
python paper_broker_service.py reset
```

## 안전 경계

현재 프로젝트는 **실계좌 주문 시스템이 아닙니다.**

향후 broker adapter는 Paper Broker 장기 검증 → read-only/account data → order payload 검증 → safety guard 순으로 진행하고, 실주문 전송은 별도의 명시적 승인 단계로 남깁니다.

## 현재 알려진 한계

- 현재 universe 중심 장기검증의 survivorship bias
- historical constituent universe 미완성
- 일봉 기반 intrabar 순서 해상도 한계
- 외부 market-data 공급자 의존
- browser Paper 상태는 계정 기반 multi-device persistence가 아님

자세한 내용과 다음 개발 순서는 [`docs/PROJECT_MASTER_PLAN.md`](docs/PROJECT_MASTER_PLAN.md)를 참조하세요.
