# swing-board · 스윙 현황판 (Vercel)

한국 스윙·미국 모멘텀 가상매매의 그날 추천, 보유 종목, 현재가·수익률, 리밸런싱 안내(신규 편입·계속 보유·익절/손절/보합 정리)를 모바일로 보는 페이지.

- `index.html` 화면, `api/board.js` 실시간 시세(네이버·야후)로 판단 계산, `board.json` 가상매매 장부 스냅샷
- `board.json`은 Claude 프로젝트의 예약 실행이 매일 갱신해서 이 폴더에 push 합니다 (`[skip ci] [skip render]` 커밋이라 swing-lab의 Render·Actions는 건드리지 않음).
- Vercel 프로젝트 Root Directory = `swing-board`. 이 폴더가 안 바뀐 커밋은 `vercel.json`의 ignoreCommand로 빌드를 건너뜁니다.
- 실제 주문은 없습니다.
