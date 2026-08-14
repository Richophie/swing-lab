# PIT 데이터 소스 결정 메모 — 2026-08-14

## 현재 확인된 사실

무료 커뮤니티 S&P 500 historical membership은 2017~2026 구간을 감도검사용으로 복원하는 데 충분히 유용했습니다. 그러나 2017년 이후 과거 구성원이면서 현재 구성원이 아닌 197개 티커를 Yahoo/yfinance로 점검했을 때, 전략 재생에 필요한 205일 warm-up과 구성 종료시점 근처 일봉을 모두 가진 종목은 약 44.67%에 그쳤습니다.

따라서 무료 가격 데이터만 사용해 나머지를 조용히 누락한 PIT 백테스트는 허용하지 않습니다. 그것은 survivorship bias를 제거한 것이 아니라 `가격이 무료로 남아 있는 과거 종목`만 살아남는 새로운 선택편향을 만들 수 있습니다.

## 실용적인 데이터 후보

### EODHD — 현재 구조에 가장 쉬운 API 후보

공식 문서 기준:

- S&P 500 `GSPC.INDX` Fundamentals 응답의 `HistoricalTickerComponents`에서 과거 구성원의 `Code`, `StartDate`, `EndDate`, `IsActiveNow`, `IsDelisted`를 제공한다고 설명합니다.
- delisted symbol list를 별도로 조회할 수 있고, delisted ticker에도 일반 EOD endpoint를 이용해 과거 일봉을 요청할 수 있다고 설명합니다.
- US symbol change history endpoint도 제공합니다.
- API 방식이라 Linux GitHub Actions에서 사용할 수 있습니다.

중요: 이 기능이 실제 우리 2017~2026 표본 전체를 완전하게 커버하는지는 구독 전에 문서만으로 `VERIFIED` 처리하지 않습니다. 토큰을 넣은 뒤 실제 sample/full coverage audit를 통과해야 합니다.

또한 공급자 원본 데이터는 public GitHub repo에 커밋하지 않습니다. Actions/local ephemeral cache에서만 사용하고, public repo에는 coverage 수치와 최종 백테스트 결과 같은 파생 결과만 저장하는 방향입니다. 실제 라이선스 약관이 파생결과 공개까지 제한한다면 그 결과도 public commit에서 제외해야 합니다.

### Norgate Data — 강한 PIT 연구 후보지만 현재 파이프라인에는 덜 간단

Norgate는 historical index constituents와 delisted securities를 명시적으로 지원하고 survivorship-bias-free backtesting 용도를 안내합니다. 다만 해당 기능은 상위 US stock package가 필요하고 Python 연결은 Windows 중심이라 현재 GitHub Actions/Linux 기반 자동 연구엔 EODHD API보다 결합비용이 큽니다.

### Alpha Vantage — lifecycle 보조자료 후보

`LISTING_STATUS` endpoint는 2010년 이후 특정 날짜의 active/delisted 미국 주식 목록을 조회할 수 있습니다. 다만 이것만으로 S&P 500 historical membership과 모든 delisted OHLCV를 함께 해결한다고 가정하지 않습니다.

## 구현된 EODHD adapter의 안전선

`eodhd_pit_adapter.py`

- 환경변수 `EODHD_API_TOKEN`이 없으면 vendor 요청 자체를 하지 않습니다.
- historical components를 파싱할 수 있습니다.
- former/delisted S&P components를 우선 sample로 뽑아 EOD coverage를 점검합니다.
- 205개 일봉 + membership 종료일 15일 이내 마지막 가격이 있어야 sample을 usable로 표시합니다.
- sample 결과가 좋아도 strict PIT source manifest를 자동으로 VERIFIED로 바꾸지 않습니다.
- production picker / Forward V1~V4 / 주문 코드를 건드리지 않습니다.
- vendor raw response/OHLCV는 public repo에 저장하지 않습니다.

## 다음 승인 단계

1. 비용 없이 adapter/unit test까지 준비한다.
2. 사용자가 유료 데이터 사용 여부를 결정한다.
3. 토큰이 생기면 먼저 25개 former/delisted sample coverage probe를 실행한다.
4. sample이 충분하면 2017~2026 전체 historical S&P component coverage를 audit한다.
5. membership boundary, ticker-change/reuse, corporate-action adjustment를 확인한다.
6. 그때만 strict source manifest를 VERIFIED 후보로 변경한다.
7. 별도 `replay_backtest_pool_pit_v1.json` 생성 후 current-universe 개발결과와 비교한다.

어떤 경우에도 PIT source 검증이 끝나기 전에 Forward V2/V3/V4 규칙을 바꾸지 않습니다.
