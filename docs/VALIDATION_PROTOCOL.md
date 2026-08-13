# Swing Lab Validation Protocol

> 상태: 공식 전략 연구/승격 규칙  
> 기준일: 2026-08-13

## 1. 목적

Swing Lab의 전략은 **최근 몇 번 잘 맞았다는 이유로 임계값을 바꾸지 않는다.** 현재 live logic을 baseline으로 동결하고, 후보 변경을 동일 데이터·동일 비용 가정에서 비교한 뒤 OOS(out-of-sample)와 walk-forward에서 살아남은 변경만 승격한다.

## 2. 가장 중요한 원칙

- 실전 strict rule과 backtest strict rule은 한 소스에서 나온다.
- 미래 수익률을 이용해 후보를 고르지 않는다.
- 한 종목의 결과를 전략 전체 성능으로 일반화하지 않는다.
- 작은 거래 수의 높은 승률을 신뢰하지 않는다.
- 수수료/슬리피지/스프레드를 뺀 결과를 실전 기대값으로 주장하지 않는다.
- 많은 파라미터를 시도할수록 과최적화 위험을 명시한다.
- 개선안이 baseline보다 좋아 보이면 반드시 OOS에서 재확인한다.
- 결과 차이를 숨기지 않는다.

## 3. 검증 계층

### 3.1 Canonical parity

목적: live와 backtest가 같은 진입 규칙과 가격계획을 쓰는지 검증.

필수:

- `strategy_rules.py` strict flags 동일
- BUY/TARGET/STOP 동일
- 시장상태 재구성 논리 동일 철학
- gap guard 동일 철학

### 3.2 Deterministic unit tests

검증 항목:

- strict signal 경계값
- trade level 계산
- 수수료/슬리피지
- gap entry reject
- gap stop
- target gap 보수 처리
- same-bar stop-first
- position sizing
- 최대 포지션 수
- same-day cash reuse 금지

### 3.3 Backtest V2

목적: Swing Lab 자체 execution model로 전략 기대값을 측정.

반드시 포함:

- 거래 수
- 승률
- 평균/중앙 거래수익률
- 총수익률
- Profit Factor
- MDD
- 평균 보유기간
- 기대값
- 비용 적용 전후 차이

### 3.4 Backtrader 독립 감사

목적: 같은 canonical signal/plan을 독립 broker engine에서 체결해 자체 구현 오류를 찾는다.

원칙:

- Swing Lab의 체결 helper를 호출하지 않는다.
- Market + Stop/Limit bracket은 Backtrader native broker에 맡긴다.
- commission/slippage도 Backtrader 경로에서 적용한다.
- entry-date mismatch와 outcome mismatch를 별도 기록한다.

현재 알려진 구조적 차이:

- 일봉에서 부모 Market 주문 체결 후 같은 봉의 child Stop/Limit 순서를 Backtrader가 Swing V2와 완전히 동일하게 재현하지 못할 수 있다.
- 이런 차이는 전략 drift와 execution-resolution 차이를 구분해 기록한다.

### 3.5 Portfolio backtest

개별 종목을 무한자본으로 각각 거래한 결과만 보지 않는다.

기본 계좌:

- 3,000,000 KRW
- 최대 3포지션
- 거래당 계획손실 1%
- 종목당 최대 40%

동시 신호 경쟁과 현금 제약을 반영한다.

### 3.6 OOS / Walk-forward

전략 변경 승인에서 가장 중요하다.

검증 데이터는 최소한 다음으로 나눈다.

- IS: 연구/설계 구간
- OOS: 한 번도 튜닝하지 않은 구간
- rolling/walk-forward 구간

가능하면 여러 시기를 반복해 한 특정 bull market에만 맞는지 확인한다.

## 4. 필수 집계 단위

전략 평가는 종목 하나가 아니라 pooled 결과가 중심이다.

필수 분해:

- 전체 기간
- 최근 2년
- 종목별
- 섹터별
- 시장 regime별
  - 상승
  - 중립
  - 약세/조심
- 변동성 regime별
- IS/OOS별
- 시간대별/연도별

## 5. 핵심 성능 지표

- trades
- win rate
- average return
- median return
- total return
- Profit Factor
- maximum drawdown
- Sharpe 또는 유사 risk-adjusted metric (가능한 경우)
- average holding period
- expectancy
- stop rate
- target hit rate
- expired rate
- 비용 drag

승률 단독 최적화 금지.

## 6. Baseline

현재 공개 baseline:

- `confirmed_pullback`
- `rsi2_trend_reversion`
- `momentum_pullback`

실험 유지:

- `volatility_breakout`

baseline 규칙은 실험 결과가 승인되기 전까지 임의 변경하지 않는다.

## 7. 실험 방법

한 번에 가능한 한 **한 요소만** 바꾼다.

예:

- RSI 범위 변경
- 120일선 거리 변경
- market filter 변경
- relative strength 추가
- flow filter 변경
- OBV/CMF 추가
- candle-volume penalty 추가
- minimum RR 변경

한 PR에서 여러 파라미터를 동시에 바꾸면 어떤 변화가 성능을 만들었는지 알 수 없으므로 원칙적으로 피한다.

## 8. 후보 연구 주제

### Relative Strength

- 20일 종목수익률 - SPY 20일 수익률
- 60일 종목수익률 - SPY 60일 수익률
- 섹터 ETF 대비 RS

처음부터 hard filter로 넣지 않고 변수로 비교한다.

### 수급 품질

후보:

- OBV slope
- CMF(20)
- 대량거래 장대음봉 penalty
- 대량거래 긴 윗꼬리 penalty
- 반전 양봉 거래량 확인

### Market regime

시장 filter가 실제 OOS 기대값을 개선하는지 확인한다.

## 9. 승격 최소 조건

정확한 숫자 cutoff는 baseline 분포에 따라 정할 수 있지만, 후보 변경은 최소한 다음을 만족해야 한다.

1. OOS expectancy > 0
2. OOS PF > 1
3. 최근 구간에서도 성능 방향이 붕괴하지 않음
4. pooled 표본이 충분함
5. 특정 소수 종목/섹터가 전체 수익 대부분을 만들지 않음
6. 비용/슬리피지 후에도 우위 유지
7. baseline 대비 실질적인 개선
8. MDD가 개선 효과에 비해 과도하게 증가하지 않음
9. Backtrader 독립감사에서 설명 불가능한 drift가 없음
10. Paper에서 execution assumption이 현실적으로 유지됨

## 10. 자동 탈락/보류 신호

- IS만 좋고 OOS가 음수
- 거래 수가 지나치게 감소
- 승률은 오르지만 기대값/PF가 악화
- 소수 종목이 수익 대부분 생성
- 특정 bull regime에서만 작동
- 수수료 적용 후 우위 소멸
- 작은 threshold 변화에 결과가 급변
- Backtrader와 진입일이 대규모로 달라짐
- 미래 데이터 leakage 가능성

## 11. 과최적화 방지

실험 기록에 반드시 남긴다.

- 테스트한 파라미터 수
- 선택하지 않은 후보값
- 연구에 사용한 기간
- OOS 기간
- 최종 선택 이유

결과가 좋아질 때까지 여러 숫자를 돌린 뒤 최고값 하나만 보고하면 안 된다.

## 12. Survivorship bias 대응

현재 종목 universe의 10년 데이터를 쓰는 검증은 survivorship bias를 포함할 수 있다.

장기 목표:

- 당시 시점의 historical constituents 확보
- delisted/merged 기업 포함 가능성 검토
- 시점별 universe reconstruction

이 작업 전에는 “20종목/현재 universe 10년 결과”를 전체 미국주식 장기 성과 증명으로 표현하지 않는다.

## 13. Paper Broker 검증 조건

실제 broker adapter 전 단계에서 충분한 Paper 기간이 필요하다.

관찰할 항목:

- pending → fill 비율
- gap cancel 비율
- fill 후 당일 stop 빈도
- target/stop/expiry 분포
- 실현 P&L
- 포지션 겹침
- 현금 부족으로 못 들어간 후보
- 실제 환율 영향
- backtest 대비 paper 차이

## 14. 실주문 단계 승격 조건

실주문 기능은 전략 승격과 별개의 안전 승격이다.

최소 단계:

1. Paper lifecycle 안정
2. 실제 broker read-only 계좌조회 검증
3. 주문 payload 생성만 검증
4. 실주문 함수 기본 비활성
5. 명시적 환경변수/권한 분리
6. 최대 주문금액/종목수 safety guard
7. duplicate order 방지
8. kill switch
9. 충분한 수동 검증
10. 별도 승인 후에만 제한적 live 논의

현재는 실주문 단계가 아니다.

## 15. PR 체크리스트 — 전략 변경

전략/엄선 hard gate 변경 PR에는 아래를 포함한다.

- [ ] 변경 가설
- [ ] baseline 명시
- [ ] 변경 파라미터 1차 원인 명시
- [ ] 동일 비용 가정
- [ ] pooled 결과
- [ ] 최근 2년 결과
- [ ] OOS 결과
- [ ] regime 분해
- [ ] 종목/섹터 concentration
- [ ] Backtrader parity
- [ ] Paper 영향
- [ ] 문서 갱신
- [ ] 기존 테스트 갱신

## 16. 기존 `STRATEGY_LAB_PLAN.md`와의 관계

`STRATEGY_LAB_PLAN.md`는 이 프로젝트의 연구 원칙을 처음 정리한 원본 메모다. 이 문서가 그 내용을 확장한 **공식 validation protocol**이며, 향후 전략 변경 기준은 본 문서를 우선한다.
