# Swing Lab 프로젝트 마스터 플랜

> 문서 상태: 공식 상위 기획서  
> 기준일: 2026-08-13  
> 적용 범위: `Richophie/swing-lab`  
> 목적: 이 문서 하나로 프로젝트의 목적, 경계, 현재 구조, 성공 기준, 개발 순서를 이해할 수 있게 한다.

## 1. 한 줄 정의

Swing Lab은 **미국주식 단기 스윙 후보를 자동 탐색하고, 현재 자리의 질을 다시 엄선한 뒤, 장중 변화·마감 확정 추천·백테스트·가상계좌까지 한 흐름으로 검증하는 개인용 의사결정 도구**다.

이 프로젝트의 핵심은 “많은 종목을 보여주는 스캐너”가 아니라 **실제로 진입을 검토할 만한 자리를 빠르게 좁히고, 그 판단을 재현 가능하게 기록하는 것**이다.

## 2. 사용 목표

### 2.1 사용자 관점

- 미국주식의 단기 스윙 후보를 빠르게 찾는다.
- 실전 선호는 대체로 3~5일 스윙, 약 3~5% 수익 구간을 노리되, 실제 목표기간과 목표가는 각 전략의 canonical trade plan을 따른다.
- 후보를 단순 RSI 과매도만으로 고르지 않고 차트, 장기추세, 수급/유동성, 시장환경, 손익비, 진입가능성을 함께 본다.
- “왜 추천됐는지 / 왜 이탈했는지 / 이후 어떻게 됐는지”를 나중에 다시 확인할 수 있어야 한다.
- 백테스트 숫자를 맹신하지 않고 실제 Paper Broker에서 주문 lifecycle까지 검증한다.

### 2.2 제품 관점

- 첫 화면에서 지금 볼 만한 후보를 빠르게 이해할 수 있어야 한다.
- 한 종목을 눌렀을 때 BUY/TARGET/STOP, 핵심 지표, 차트, 백테스트, 투자금 계산까지 한 흐름으로 연결한다.
- 전략 점수는 성공확률처럼 보이지 않게 한다. 점수는 현재 후보를 정렬하기 위한 상대적 품질 점수다.
- 복잡한 퀀트 터미널보다 **실전 판단에 필요한 정보 우선순위**를 더 중요하게 본다.

## 3. 프로젝트가 하지 않는 것

- 현재 단계에서 실계좌 주문을 전송하지 않는다.
- 백테스트 승률을 미래 성공확률로 표현하지 않는다.
- 한 종목의 최근 실패/성공만 보고 전략 임계값을 즉흥적으로 변경하지 않는다.
- 뉴스/LLM 의견을 가격 데이터 기반 전략보다 먼저 사용하지 않는다.
- 장중 순간 후보를 공식 성과 기록으로 간주하지 않는다.

## 4. 현재 제품 플로우

1. **미국 종목 universe 구성**
2. **가격/지표 데이터 수집**
3. **공개 3전략의 canonical strict signal 판정**
4. **전략별 S 신호 생성**
5. **현재 자리 엄선**
   - 수급/유동성
   - 손익비
   - 시장 상태
   - 진입 가능성
   - ATR 손절여유
   - 일부 전략의 20일선 첫 눌림 overlay
6. **실시간 후보 노출**
7. **장중 ENTER/EXIT 변화 기록**
8. **미국장 마감 후 공식 추천 동결**
9. **다음 거래일부터 결과 판정**
10. **상세 차트/백테스트/투자금 계산 제공**
11. **Paper Broker에서 실제 주문 lifecycle 검증**
12. **독립 Backtrader 감사 + OOS/Walk-forward 연구**

## 5. 공개 전략

현재 메인 공개 전략은 3개다.

- `confirmed_pullback` — 확인형 눌림반등
- `rsi2_trend_reversion` — RSI2 추세내 과매도
- `momentum_pullback` — 모멘텀 눌림 지속

`volatility_breakout` — 변동성 수축 돌파는 실험 전략으로 유지하며 메인 엄선 추천에서는 제외한다.

전략의 strict signal과 BUY/TARGET/STOP 공식은 `strategy_rules.py`가 canonical source of truth다.

## 6. 추천의 세 단계

Swing Lab은 “추천”을 하나의 상태로 취급하지 않는다.

### 6.1 실시간 후보

- 형성 중인 미국 일봉 데이터를 기준으로 변할 수 있다.
- RSI, 볼린저 위치, 현재가, 거래량 등이 바뀌면서 후보에 들어오거나 빠질 수 있다.
- 사용자가 지금 관찰할 대상을 찾기 위한 목록이다.

### 6.2 장중 포착 · 이탈 로그

- 엄선 후보가 처음 들어오면 `ENTER`를 기록한다.
- 이후 엄선 기준에서 빠지면 `EXIT`를 기록한다.
- 이탈 시 가능한 경우 실제 깨진 조건을 기록한다.
  - 전략 S 점수 기준 이탈
  - 수급 점수 미달
  - 손익비 1.20:1 미달
  - 시장 상태 조심
  - 진입구간 이탈
  - ATR 손절여유 부족
  - 엄선점수 72 미달
- 이 로그는 장중 후보의 변화 원인을 추적하기 위한 것이며 공식 성과 통계가 아니다.

### 6.3 마감 확정 추천

- 미국 동부시간 16:05 이후의 스캔에서만 공식 추천으로 동결한다.
- 실제 SPY의 최근 거래일을 기준으로 market date를 결정한다.
- 같은 날 이미 동결된 동일 종목/전략은 다시 덮어쓰지 않는다.
- 공식 추천 성과는 **마감 확정 추천만** 사용한다.
- 결과 판정은 추천일 다음 거래일부터 시작한다.

## 7. 엄선 정책

전략별 raw S 신호와 최종 엄선은 분리한다.

현재 최종 엄선 hard gate:

- 손익비 `>= 1.20:1`
- 수급/유동성 점수 `>= 42`
- 시장 상태가 `조심`이 아님
- 현재 진입이 허용 가능한 상태
- 손절여유가 최소 `1.5 ATR`
- 최종 엄선점수 `>= 72`

엄선점수는 대략 다음 정보를 결합한다.

- 전략 신호 품질
- 수급/유동성 품질
- 손익비
- 시장 상태
- 진입상태
- ATR 손절여유
- 일부 눌림 전략의 20일선 첫 눌림 overlay

백테스트 결과는 **오늘 후보의 합격/탈락 hard gate로 사용하지 않는다.**

## 8. 계좌 모델

기본 검증 계좌:

- 초기자금: 3,000,000 KRW
- 최대 동시 포지션: 3
- 거래당 계획손실: 계좌의 1%
- 종목당 최대 노출: 계좌의 40%

Backtest portfolio 모델은 KRW 명목 노출 기준으로 비교한다. 실제 USD 환율, 정수 주식 수량, 현금 차감은 Paper Broker에서 별도로 검증한다.

## 9. 체결 철학

낙관적인 체결을 피한다.

- 신호 당일에는 진입하지 않고 다음 거래일 시가를 기준으로 한다.
- 다음날 시가가 canonical gap guard를 크게 벗어나면 진입하지 않는다.
- 손절가 아래 갭다운 시 손절가 체결로 미화하지 않는다.
- 목표가 위 갭업 시 유리한 시가 전체를 먹었다고 가정하지 않는다.
- 같은 일봉에서 TARGET과 STOP을 모두 터치하면 보수적으로 STOP을 먼저 적용한다.
- 수수료, 슬리피지, 반스프레드를 포함한다.

## 10. 검증 계층

### Layer A — 규칙 일치

`strategy_rules.py`를 live와 backtest가 함께 사용한다.

### Layer B — Backtest V2

현실적인 비용, gap, stop-first, finite capital을 적용한다.

### Layer C — Backtrader 독립 감사

canonical signal/price plan만 공유하고 체결은 Backtrader native broker가 수행한다.

### Layer D — Paper Broker

정수 주식 수량, 실제 환율, 예약현금, 주문 상태, P&L을 검증한다.

### Layer E — OOS / Walk-forward / regime 연구

전략을 개선할 때 반드시 baseline과 분리 검증한다.

### Layer F — 실제 증권사 adapter

Paper 검증을 충분히 통과한 뒤 주문 payload/계좌조회부터 연결한다. **실주문 전송은 별도 명시적 단계이며 기본 비활성이다.**

## 11. 현재 시스템 구성

- `app.py` — Flask API 및 웹 기능
- `paper_entry.py` — 배포용 Flask 진입점 + Paper restore API
- `market_data.py` — 가격/지표/universe/시장상태
- `strategy_rules.py` — canonical strict signal + trade levels
- `strategy_engine.py` — 전략 점수/설명
- `scanner.py` — 스캔 + 엄선
- `signal_log.py` — 장중 ENTER/EXIT 기록
- `journal.py` — 마감 확정 추천 + 결과 판정
- `backtest_engine.py` — Backtest V2
- `portfolio_backtest.py` — finite-capital 계좌 백테스트
- `backtrader_audit.py` — 독립 체결 감사
- `audit_matrix.py` — 20종목 × 3전략 장기 감사
- `paper_broker.py` — 가상 주문 lifecycle
- `paper_broker_service.py` — Paper 서비스 계층
- `paper_restore.py` — 브라우저 백업 복구
- `walkforward.py` — OOS/walk-forward 검증
- `static/*` — 대시보드 UI 및 저장 데이터
- `.github/workflows/*` — 자동 스캔 및 PR 검증
- `render.yaml` — Render 배포 설정

## 12. 배포 구조

Production:

- Render service: `swing-lab`
- Start command: `gunicorn paper_entry:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180`
- GitHub `main` 코드 커밋 → Render 자동 배포
- 30분 장중 스캔 데이터 커밋은 `[skip render]`로 Render 재배포를 건너뛴다.

## 13. 성공 기준

단순히 “백테스트 승률이 높다”를 성공으로 보지 않는다.

제품 성공 조건:

- 추천 이유가 재현 가능하다.
- 후보 진입/이탈 변화가 기록된다.
- 공식 추천 성과가 장중 변화와 섞이지 않는다.
- Paper Broker가 실제 주문 흐름과 현금 제약을 안정적으로 재현한다.
- 전략 개선은 OOS에서 baseline보다 실제 우위가 있다.
- UI가 복잡한 지표를 숨기지 않으면서도 빠른 판단을 돕는다.
- 장애가 생겨도 저장된 스캔 데이터로 첫 화면이 빠르게 복구된다.

## 14. 현재 알려진 한계

- 현재 universe 기반 검증에는 survivorship bias 가능성이 있다.
- 장기 성과를 주장하려면 historical constituent universe가 필요하다.
- 일봉 데이터만으로 같은 봉 안의 정확한 intrabar 순서를 완전히 재구성할 수 없다.
- Backtrader와 Swing V2는 이 부분에서 일부 체결 차이가 날 수 있으며 숨기지 않고 감사한다.
- 외부 시장데이터 공급자 장애 가능성이 있다.
- Paper 상태는 브라우저별 익명 상태이며 계정 기반 다중기기 영속 저장은 아니다.
- 실계좌 연결은 아직 제품 목표의 후속 단계이며 활성화되어 있지 않다.

## 15. 개발 우선순위

### 현재

- 스캐너/엄선
- 장중 포착·이탈
- 마감 확정 기록
- Backtest V2
- Backtrader 감사
- Paper Broker
- 웹 UI
- Render 자동배포

### 다음

1. 운영 문서와 코드 지속 동기화
2. Paper Broker 장기간 실사용 기록 축적
3. 후보/추천 통계 대시보드 개선
4. historical universe 기반 장기검증
5. OOS/walk-forward/regime 리포트 고도화
6. 전략별 calibration 및 기대값 비교
7. Toss API read-only/account/order-payload adapter 연구
8. 충분한 Paper 검증 이후에만 별도의 실주문 안전 설계 논의

## 16. 문서 우선순위

- 프로젝트 목적/경계/로드맵: 이 문서
- 매매/추천 규칙: `TRADING_RULES.md`
- 전략 변경 및 연구 규칙: `VALIDATION_PROTOCOL.md`
- 자동화/배포/장애 대응: `SYSTEM_OPERATIONS.md`
- 제품/UI 원칙: `PRODUCT_UI_GUIDE.md`
- 중요한 결정 이력: `DECISION_LOG.md`

코드의 현재 실행값과 문서가 충돌하면 **실제 현재 동작 확인은 코드가 우선**한다. 그러나 전략/안전/제품 원칙을 바꾸는 코드 변경은 반드시 해당 공식 문서를 같은 PR에서 함께 갱신하는 것을 원칙으로 한다.
