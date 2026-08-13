# RSI2 Live-like Selector Research · 2026-08-13

> 상태: 연구 완료 / 라이브 규칙 변경 보류  
> 목적: canonical RSI2 자체가 아니라 실제 Swing Lab의 `strict → S → flow/RR/market → elite → next-open` 경로에 가까운 표본에서 falling-knife 방지 후보를 비교한다.

## 1. 왜 다시 연구했나

이전 NET RR 연구에서 RSI2의 OOS/최근 성과가 약했지만, 그 표본은 canonical strict 신호 전체를 중심으로 본 것이었다.

실제 사이트는 strict RSI2 신호 뒤에 다음을 추가로 거른다.

- strategy score >= 85
- flow quality >= 42
- precise gross RR >= 1.20
- market != `조심`
- elite score >= 72
- 다음 거래일 시가 gap guard
- 수수료/스프레드/슬리피지

따라서 RSI2 규칙을 바꾸기 전에 이 live-like selector를 역사적으로 재구성하고 단순한 반전확인/시장필터 후보를 비교했다.

## 2. 표본과 방법

현재-name 20종목, 10년 일봉.

live-like 조건을 통과한 signal-day 후보는 총 233개였고, 실제 비중복 체결 시 baseline 거래는 148건이었다.

각 종목별:

- 첫 70% row = IS
- 마지막 30% row = OOS
- 최근 약 504 trading rows = recent 2y

각 variant는 baseline 완성거래를 사후 필터링하지 않고 **처음부터 독립 재시뮬레이션**했다. 한 거래가 필터에서 탈락하면 그 기간의 뒤 신호를 받을 수 있다.

비교 variant:

1. baseline live-like
2. 가격반전: `close > previous close OR close > open`
3. MACD histogram 개선
4. RSI14 > 전일
5. RSI14 >= 3일 전
6. 가격반전 AND MACD 개선
7. 가격반전/MACD/RSI상승 중 2개 이상
8. 시장상태 `좋음`만
9. 가격반전 AND 시장 `좋음`
10. close >= 120DMA

## 3. 핵심 결과

### Baseline live-like

- 전체: 148건 · 평균 -0.796% · PF 0.571
- OOS: 59건 · 평균 -0.470% · PF 0.719
- 최근2년: 36건 · 평균 -0.531% · PF 0.702

현재 20종목 고정표본에서는 실제 엄선에 더 가까이 좁혀도 RSI2 기대값이 여전히 음수였다.

## 4. 반전확인 가설은 지지되지 않았다

### 가격반전

- 전체 33건, baseline의 22.3%
- OOS 10건 · 평균 -0.339% · PF 0.777
- 최근2년 5건 · 평균 -0.296% · PF 0.791

손실폭은 약간 줄지만 거래의 약 78%를 없애고 여전히 음수다.

### MACD 개선

- 전체 3건
- OOS 1건 · -3.74%

실질적으로 신호가 소멸한다.

### RSI14 상승 / 2-of-3

- 각각 전체 약 3건 수준
- 최근 표본은 1건 수준

검증 가능한 거래 수를 유지하지 못한다.

### 가격반전 + 시장 좋음

- 전체 20건
- OOS 6건
- 최근2년 3건

최근 숫자가 플러스여도 표본이 지나치게 작아 의미 있는 승격 근거가 아니다.

### 결론

RSI2가 너무 일찍 falling knife를 잡는다는 직관만으로 `반전 캔들`, `MACD 개선`, `RSI 턴`을 hard confirmation으로 붙이는 것은 현재 자료에서 지지되지 않는다.

특히 RSI2의 본질이 극단적 단기 과매도이므로 반전확인을 기다릴수록 원래 신호와 교집합 자체가 거의 사라지는 것으로 보인다.

## 5. 가장 유의미한 후보: 시장 `좋음`만

`market_good_only` 결과:

- 전체: 95건 · baseline 대비 64.2% coverage · 평균 -0.482% · PF 0.696
- IS: 54건 · 평균 -0.744% · PF 0.571
- OOS: 41건 · 평균 -0.137% · PF 0.902
- 최근2년: 28건 · 평균 **+0.115%** · PF **1.089** · 승률 53.6%

baseline 대비:

- OOS 평균 -0.470% → -0.137%
- OOS PF 0.719 → 0.902
- 최근2년 평균 -0.531% → +0.115%
- 최근2년 PF 0.702 → 1.089

즉 단순 반전확인보다 **시장 regime**가 RSI2 품질을 설명할 가능성이 더 커 보인다.

## 6. 그러나 아직 라이브 승격하지 않는 이유

최근2년 28건, OOS 41건으로 여전히 작다.

종목별 효과도 균일하지 않다.

OOS에서 개선 예:

- AAPL: +0.07% → +0.90%
- META: -1.59% → -0.47%
- JPM: -0.37% → +0.70%
- F: -2.98% → +2.16% (단 1건)

반대로:

- MSFT는 악화
- CAT는 악화
- HD는 여전히 크게 음수
- AMZN은 개선돼도 여전히 음수

최근2년도 AAPL/JPM 등은 개선되지만 AMZN/META 등은 나쁘다.

따라서 현재 결과는 `시장 좋음 only`를 **유력 후보**로 올리기에는 충분하지만 실제 공개 RSI2 strict rule을 바꾸기에는 부족하다.

## 7. 다음 검증

다음 단계는 parameter search를 더 늘리는 것이 아니다.

`market_good_only` 하나를 후보로 고정하고 더 넓은 현재 liquid universe에서 재검증한다.

필수 비교:

- baseline live-like vs market_good_only
- 거래 수/coverage
- OOS PF / 기대값
- 최근2년
- 종목별 분포
- sector별 분포
- 결과가 소수 종목에 집중되는지

가능하면 이후 historical-universe 또는 더 강한 walk-forward 검증으로 확장한다.

## 8. 이번 결정

라이브 변경 없음.

유지:

- 현재 RSI2 canonical strict signal
- 현재 market `조심` 제외 규칙

연구 후보:

- `RSI2는 market state == 좋음일 때만 elite 허용`

폐기/낮은 우선순위:

- 단순 가격반전 hard gate
- MACD improvement hard gate
- RSI turn hard gate
- 2-of-3 confirmation

다음 연구의 목표는 **시장 좋음 filter의 표본 확대 검증**이다.

## 9. 한계

- 현재 살아있는 20종목 고정표본 → survivorship/current-universe bias
- 여러 confirmation variant를 비교했으므로 best-result selection bias 존재
- sector/industry 분산이 충분하지 않음
- historical live flow를 일봉 기반으로 근사

따라서 이 연구의 숫자는 최종 기대수익률 추정치가 아니라 다음 후보를 좁히는 용도다.
