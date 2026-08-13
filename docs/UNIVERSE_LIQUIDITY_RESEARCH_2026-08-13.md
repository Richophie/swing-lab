# Universe Dollar-Liquidity Research · 2026-08-13

> 상태: 연구 완료 / **production universe 현행 500 유지**

## 질문

현재 Swing Lab은 시총·가격·3개월 평균거래량 기준으로 상위 유동 대형주 약 500개를 먼저 고른다.

다음 가설을 검증했다.

1. 시가총액 정렬보다 `가격 × 3개월 평균 일거래량`(달러거래대금 proxy) 정렬이 더 좋은가?
2. 현재 500을 유지하면서 고유동성 종목을 추가하면 실제 엄선 후보 발견이 늘어나는가?
3. bid/ask spread를 production hard filter로 쓸 수 있을 만큼 데이터 커버리지가 충분한가?

## 연구 표본

- 미국 상장 operating-company universe: 약 5,700개
- broad quote pool: 약 1,400개
- broad pool 최소조건:
  - 가격 $5+
  - 3개월 평균 거래량 20만주+
  - 시가총액 $500M+
- 비교 시점: 2026-08-13 현재
- 전략/엄선 로직은 production과 동일

## 결과 1 · 현재 500의 유동성은 이미 높다

현재 market-cap-oriented 500:

- 달러 일거래대금 proxy 하위 10%: 약 **$199M/day**
- 중앙값: 약 **$486M/day**
- 상위 10%: 약 **$2.28B/day**
- 최소값: 약 **$32M/day**

즉 현재 500은 3백만원 규모의 스윙 계좌에서 유동성 부족이 핵심 병목이라고 보기 어려운 수준이다.

## 결과 2 · dollar top500 교체는 악화

현재 500:

- raw public S 종목: 6
- elite 종목: 2
- raw S / 100종목: 1.20
- elite / 100종목: 0.40

Dollar-volume top500:

- raw public S 종목: 1
- elite 종목: 0

단순 달러거래대금 순위로 기존 500을 교체하면 유효 후보 발견이 오히려 줄었다.

## 결과 3 · dollar top800도 교체안으로는 비효율

Dollar top800:

- raw public S 종목: 6
- elite 종목: 1
- raw S / 100종목: 0.75
- elite / 100종목: 0.12

현재 500보다 종목 수는 60% 많지만 elite 발견 수는 더 적었다.

## 결과 4 · additive expansion

가장 현실적인 후보는 기존 500을 버리지 않고 dollar top800의 추가 종목만 더하는 방식이다.

### 현재 500

- 500종목
- raw S: 6
- elite: 2
- raw S: ACGL, BUD, FMX, L, MSCI, WRB
- elite: BUD, FMX

### 현재500 + dollar800 union

- **826종목**
- 기존 대비 추가: **326종목**
- raw S: 8
- elite: 2
- 새 raw S: **BAP, LNT**
- 새 elite: **0**

즉 스캔 대상은 약 **65% 증가**하지만 실제 엄선 매매후보는 하나도 증가하지 않았다.

현재 한 시점의 표본만으로 미래 발견률을 완전히 단정할 수는 없지만, production runtime과 외부 데이터 호출량을 크게 늘릴 근거로는 부족하다.

## Spread 데이터

Yahoo screener quote에서 bid/ask가 제공되는 비율은 대략 28~33% 수준이었다.

따라서 현재 데이터 소스만으로:

- spread hard filter
- spread 기반 universal ranking

을 넣으면 결측치 때문에 불필요한 편향이 생길 수 있다.

Spread는 향후 더 안정적인 quote source가 확보될 때 다시 연구한다.

## Production 결정

### 유지

- `SCAN_CANDIDATE_LIMIT = 500`
- 현재 시총/가격/평균거래량 prefilter
- scanner의 기존 flow 내부 `avg_dollar_volume_20d` 품질점수

### 채택하지 않음

- dollar-volume top500으로 교체
- dollar-volume top800으로 교체
- current500 + 326종목 추가
- Yahoo bid/ask spread hard filter

## 의미

현재 병목은 **유니버스가 너무 좁아서 좋은 후보를 못 찾는 것**보다, 이미 충분히 유동적인 500개에서 좋은 setup이 실제로 드물게 발생하는 쪽에 가깝다.

따라서 다음 개선 우선순위는 종목 수 확대가 아니라 **동시에 잡힌 2~3개 후보가 같은 위험요인에 몰려 있는지**를 확인하는 portfolio correlation/concentration 관리다.

## 다음 연구

60거래일 trailing return correlation을 신호일 기준으로 계산해:

1. 현재 RR 우선 3포지션
2. low-correlation priority
3. correlation 0.75 / 0.60 hard cap
4. 고상관 거래 half-risk

을 finite 3백만원 계좌에서 OOS/recent로 비교한다.
