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
- `backtest_engine.py` — 실전과 동일한 canonical 신호/가격계획을 사용하는 벡터 백테스트
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
- 한 일봉에서 목표와 손절을 모두 터치한 경우 보수적으로 손절을 먼저 적용합니다.

## 자동 실행

GitHub Actions의 `Market Scan Cache`가 장중 주기적으로:

1. 모듈 문법 검사
2. 최신 스캔 생성
3. QA 통과 여부 확인
4. 날짜별 추천 기록 및 결과 갱신
5. 캐시 파일 커밋

순서로 실행됩니다.

Render는 `gunicorn app:app`으로 현재 `app.py`만 실행합니다.
