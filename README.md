# Swing Lab · 오늘의 스윙자리

개인용 미국주식 스윙 후보 탐색·검증 도구입니다.

## 현재 구조

운영 코드는 버전 파일을 연쇄 상속하지 않습니다.

- `app.py` — Flask API / 웹 진입점
- `market_data.py` — 가격 데이터, 지표, 미국 종목 universe, 시장 상태
- `strategy_engine.py` — 4개 독립 전략과 전략별 BUY/TARGET/STOP
- `scanner.py` — 미국 종목 스캔과 추천 캐시 생성
- `journal.py` — 날짜별 추천 스냅샷과 결과 판정
- `backtest_engine.py` — 전략별 빠른 백테스트
- `walkforward.py` — OOS / Walk-forward 검증
- `stock_names.py` — 한글 종목명 단일 관리
- `qa.py` — 회귀/구조 검증
- `static/dashboard.html` — 단일 대시보드 UI

## 공개 전략

1. 확인형 눌림반등
2. RSI2 추세내 과매도
3. 모멘텀 눌림 지속

변동성 수축 돌파 전략은 메인 추천에서 숨기고 기록/검증 데이터로만 유지합니다.

## 자동 실행

GitHub Actions의 `Market Scan Cache`가 장중 주기적으로:

1. 모듈 문법 검사
2. 최신 스캔 생성
3. QA 통과 여부 확인
4. 날짜별 추천 기록 및 결과 갱신
5. 캐시 파일 커밋

순서로 실행됩니다.

Render는 `gunicorn app:app`으로 현재 `app.py`만 실행합니다.
