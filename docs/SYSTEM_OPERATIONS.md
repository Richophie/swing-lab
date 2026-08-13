# Swing Lab System Operations

> 상태: 공식 운영/배포/장애 대응 문서  
> 기준일: 2026-08-13

## 1. 목적

Swing Lab의 자동 스캔, 저장 데이터, GitHub Actions, Render 배포, Paper Broker, 장애 대응을 한 문서에 정리한다.

목표는 **코드 배포와 데이터 갱신을 분리하고, 외부 데이터 공급자가 느려도 저장된 결과로 웹 첫 화면이 최대한 빨리 뜨게 하는 것**이다.

## 2. Production 구성

Repository:

- `Richophie/swing-lab`
- production branch: `main`

Render:

- service: `swing-lab`
- runtime: Python
- start command:

```bash
gunicorn paper_entry:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 180
```

`paper_entry.py`는 `app.py`의 Flask app을 import하고 `/api/paper/restore` 복구 route를 추가한다.

## 3. 코드 배포와 데이터 갱신의 분리

### 코드 변경

`main`에 코드 커밋이 들어오면 Render automatic deploy가 실행된다.

### 자동 스캔 데이터 변경

장중 자동 스캔은 `static/*.json` 데이터를 갱신하고 다음 형식으로 커밋한다.

```text
data: refresh live signals and confirmed journal [skip render]
```

`[skip render]`를 사용해 **30분 데이터 갱신마다 웹 서버가 재배포되는 문제를 방지**한다.

## 4. Market Scan Cache workflow

파일:

- `.github/workflows/market-scan.yml`

현재 schedule:

```text
*/30 13-22 * * 1-5
```

즉 UTC 기준 평일 13~22시 동안 30분 간격이다. 미국시장/서머타임과 실제 목적에 맞는지 주기적으로 검토한다.

workflow 순서:

1. checkout
2. Python 3.11
3. requirements 설치
4. core module compile
5. 특정 과거 journal repair/rebuild 단계
6. `scanner.py` — 최신 후보 생성
7. `refresh_fx_cache.py` — USD/KRW cache 갱신
8. `signal_log.py` — 장중 ENTER/EXIT 기록
9. `qa.py` — architecture QA
10. `journal.py` — 마감 확정 및 결과 업데이트
11. JSON data commit

## 5. 저장 데이터

### `static/latest_scan.json`

최신 mutable live scan.

주요 내용:

- scanned_at
- market
- results
- public S count
- aggregate eligible count
- strategy signals
- trade plans
- elite checks

### `static/signal_events.json`

장중 lifecycle.

- current active elite signals
- ENTER events
- EXIT events
- exit reason/code/details
- 최대 최근 1500 events 유지

### `static/trade_history.json`

마감 확정 추천과 결과 기록.

- `CONFIRMED_CLOSE`
- 추천 당시 BUY/TARGET/STOP
- 추천일 다음 거래일부터 결과 판정
- SUCCESS / STOP / EXPIRED 계열

### `static/fx_cache.json`

웹 첫 화면이 외부 환율 API를 기다리지 않도록 저장하는 USD/KRW cache.

원칙:

- first-load API는 cache가 있으면 network 환율 조회를 기다리지 않는다.
- 자동 workflow에서 cache를 갱신한다.
- 환율 갱신 실패 시 마지막 정상 cache를 유지하는 방향을 우선한다.

## 6. 웹 first-load 원칙

첫 화면은 가능한 한 저장 데이터 기반이어야 한다.

금지:

- `/api/latest` 요청 하나가 Yahoo 등 외부 서비스 응답을 무한정 기다리게 만들기
- 첫 렌더링 전에 전체 universe 재스캔하기
- 환율 하나가 실패했다고 추천 전체를 숨기기

권장:

- 저장 scan 즉시 반환
- 저장 FX 즉시 반환
- 실시간 refresh는 별도 user action 또는 background path
- error가 나도 shell과 마지막 정상 데이터는 보여주기

## 7. Frontend 안정성 원칙

2026-08-13 UI 변경 중 두 개의 `MutationObserver`가 동일 제목을 서로 바꾸면서 무한 루프가 발생한 적이 있다.

재발 방지:

- `document.body` 전체를 감시하는 observer는 원칙적으로 피한다.
- observer는 필요한 container로 scope한다.
- observer callback이 자기 자신의 DOM 변경을 다시 trigger하는지 확인한다.
- dynamic UI script는 idempotent해야 한다.
- `dataset.*` 또는 명시적 state로 이미 처리한 element를 다시 처리하지 않는다.
- 새 JS는 `node --check`에 포함한다.
- 새 JS asset은 `tests/test_ui_wiring.py`의 wiring regression에 포함한다.
- cache bug 가능성이 있으면 query version을 올린다.

## 8. PR Core Validation

파일:

- `.github/workflows/pr-core-validation.yml`

핵심 단계:

1. Python compile
2. JavaScript syntax check
3. canonical strategy parity
4. Backtest V2 tests
5. Backtrader independent tests
6. Paper Broker lifecycle
7. Paper browser restore
8. signal history / publication tests
9. startup/deploy stability
10. detail/backtest/Paper UI regression
11. real 10y × 20 stocks × 3 strategies audit
12. audit artifact upload

전략/주문/데이터 구조를 변경하는 PR은 이 gate를 통과한 뒤 merge하는 것이 기본이다.

## 9. Render 장애 진단 순서

사용자 증상별로 순서를 고정한다.

### A. HTML 껍데기는 뜨는데 데이터가 계속 로딩

확인:

1. latest Render deploy status
2. `/api/latest` path가 외부 network를 기다리는지
3. `static/latest_scan.json`이 정상인지
4. FX cache 존재 여부
5. browser console / frontend runtime error
6. stale JS cache

### B. 검은 화면 / 브라우저가 멈춤

우선 frontend infinite loop를 의심한다.

확인:

1. 최근 UI JS 변경
2. MutationObserver
3. requestAnimationFrame / setInterval loop
4. 반복 DOM rewrite
5. overlay initial state
6. cache-busted script version

필요하면 기능보다 **페이지가 뜨는 것**을 우선해 최근 장식 JS를 안전모드로 제거한다.

### C. Render deploy는 success인데 페이지가 안 뜸

확인:

- start command
- import exception
- gunicorn timeout
- startup network call
- app route import cycle
- runtime log

현재 start entry는 `paper_entry:app`이다.

### D. 추천 데이터가 비어 있음

확인:

- workflow latest run
- `latest_scan.json` status
- failed_count
- market state
- candidate universe
- S signals 존재 여부
- elite gate 때문에 aggregate만 0인지

raw S와 elite 결과를 혼동하지 않는다.

## 10. Paper Broker 상태

Paper API는 browser client ID를 사용해 상태를 분리한다.

기본 원칙:

- live brokerage credential 없음
- real order send 없음
- `live_trading_enabled` false
- browser localStorage backup은 Render ephemeral state 복구용
- restore는 server state가 비었을 때의 recovery 성격
- active server state를 stale browser backup으로 덮어쓰지 않는다.

현재 한계:

- authenticated user account 없음
- 다중기기 자동 sync 없음
- Render persistent database를 쓰는 구조 아님

## 11. 외부 데이터 의존성

현재 주가/시장 데이터는 Yahoo Finance/yfinance 의존 구간이 있다.

운영 원칙:

- network call에는 timeout을 둔다.
- 저장 가능한 결과는 cache한다.
- UI first load와 장시간 research download를 분리한다.
- 외부 장애를 전략 실패로 기록하지 않는다.
- workflow 실패와 “신호 없음”을 구분한다.

## 12. 데이터 커밋 정책

자동 생성 JSON은 bot commit으로 저장한다.

코드 변경과 데이터 변경을 같은 의미로 취급하지 않는다.

- code commit → Render deploy 가능
- data-only scheduled commit → `[skip render]`

rebase/push 충돌 시 최신 main 위에 자동 데이터 변경을 다시 적용한다.

## 13. 배포 전 체크리스트

UI만 변경:

- [ ] JS syntax
- [ ] no global observer loop
- [ ] cache version
- [ ] detail open/close regression
- [ ] paper UI regression
- [ ] mobile overflow

전략 변경:

- [ ] `VALIDATION_PROTOCOL.md`
- [ ] parity
- [ ] backtest
- [ ] Backtrader
- [ ] Paper 영향
- [ ] docs

API/서버 변경:

- [ ] start entry 확인
- [ ] startup network blocking 없음
- [ ] route error handling
- [ ] existing `/api/latest` compatibility
- [ ] Render timeout 고려

## 14. 긴급 hotfix 원칙

서비스가 실제로 안 뜨는 장애는 다음 순서로 대응한다.

1. 원인 범위 축소
2. 최소 hotfix
3. cache bust 필요 여부 확인
4. production deploy
5. deploy `success` 확인
6. 이후 regression test 보강
7. `DECISION_LOG.md`에 구조적 원인이면 기록

UI 미세조정보다 서비스 복구를 우선한다.

## 15. 운영 변경 기록

다음 변경은 `DECISION_LOG.md`에 남긴다.

- production start command 변경
- 스캔 schedule 변경
- official publish 시각 변경
- data provider 변경
- broker adapter 추가
- Paper persistence 구조 변경
- 실주문 safety boundary 변경
- cache architecture 변경

## 16. 현재 production 사실

2026-08-13 기준:

- Render start: `paper_entry:app`
- main push 자동배포
- scheduled scan data commit은 `[skip render]`
- persisted FX cache 사용
- live trading disabled
- browser Paper recovery 지원

이 항목이 코드와 달라지면 같은 PR에서 본 문서를 갱신한다.
