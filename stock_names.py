from __future__ import annotations
import re

# Single display-name source. Extend here only; UI/scanner never hard-code names.
KO_NAMES={
'AAPL':'애플','MSFT':'마이크로소프트','NVDA':'엔비디아','AMZN':'아마존','META':'메타 플랫폼스','GOOGL':'알파벳','GOOG':'알파벳','TSLA':'테슬라','AVGO':'브로드컴','AMD':'AMD','INTC':'인텔','QCOM':'퀄컴','MU':'마이크론 테크놀로지','ARM':'Arm 홀딩스','ASML':'ASML','TSM':'TSMC','AMAT':'어플라이드 머티어리얼즈','LRCX':'램 리서치','KLAC':'KLA','SMCI':'슈퍼마이크로컴퓨터','PLTR':'팔란티어','ORCL':'오라클','CRM':'세일즈포스','ADBE':'어도비','NOW':'서비스나우','IBM':'IBM','CSCO':'시스코','PANW':'팔로알토 네트웍스','CRWD':'크라우드스트라이크','ANET':'아리스타 네트웍스',
'JPM':'JP모건 체이스','BAC':'뱅크오브아메리카','WFC':'웰스파고','GS':'골드만삭스','C':'씨티그룹','V':'비자','MA':'마스터카드','PYPL':'페이팔','SOFI':'소파이','COIN':'코인베이스','HOOD':'로빈후드','AXP':'아메리칸 익스프레스','SPGI':'S&P 글로벌',
'WMT':'월마트','COST':'코스트코','HD':'홈디포','LOW':'로우스','TGT':'타깃','TJX':'TJX 컴퍼니스','NKE':'나이키','SBUX':'스타벅스','MCD':'맥도날드','KO':'코카콜라','PEP':'펩시코','PG':'프록터앤드갬블','PM':'필립모리스','MDLZ':'몬델리즈','KHC':'크래프트 하인즈','HRL':'호멜 푸즈','SYY':'시스코','M':'메이시스','WRBY':'워비 파커',
'JNJ':'존슨앤드존슨','LLY':'일라이 릴리','NVO':'노보 노디스크','PFE':'화이자','MRK':'머크','ABBV':'애브비','BMY':'브리스톨 마이어스 스퀴브','GILD':'길리어드 사이언스','AMGN':'암젠','UNH':'유나이티드헬스','TMO':'써모 피셔 사이언티픽','DHR':'다나허','ABT':'애보트','ISRG':'인튜이티브 서지컬','HIMS':'힘스앤허스 헬스',
'XOM':'엑슨모빌','CVX':'셰브론','COP':'코노코필립스','SLB':'SLB','FCX':'프리포트맥모란','CAT':'캐터필러','DE':'디어','GE':'GE 에어로스페이스','BA':'보잉','HON':'허니웰','RTX':'RTX','LMT':'록히드마틴','NOC':'노스롭그루먼','GM':'제너럴모터스','F':'포드','UBER':'우버','BKNG':'부킹홀딩스','DIS':'월트디즈니','NFLX':'넷플릭스','SHOP':'쇼피파이','PINS':'핀터레스트','RBLX':'로블록스','APP':'앱러빈','TOST':'토스트',
'O':'리얼티 인컴','PLD':'프로로지스','KIM':'킴코 리얼티','INVH':'인비테이션 홈즈','VTR':'벤타스','VTRS':'비아트리스','HR':'헬스피크 프로퍼티스','HST':'호스트 호텔스앤리조츠','UDR':'UDR','AMT':'아메리칸 타워','CCI':'크라운 캐슬',
'SIRI':'시리우스XM','RIOT':'라이엇 플랫폼스','CORZ':'코어 사이언티픽','CLSK':'클린스파크','MARA':'마라 홀딩스','OUST':'아우스터','NBIS':'네비우스 그룹','AUR':'오로라 이노베이션','BFLY':'버터플라이 네트워크','FRSH':'프레시웍스','ACVA':'ACV 옥션스','EBC':'이스턴 뱅크셰어스','LION':'라이온 그룹 홀딩','BGC':'BGC 그룹','CFG':'시티즌스 파이낸셜 그룹','XYZ':'블록','IBN':'ICICI 뱅크','VSH':'비쉐이 인터테크놀로지','HPQ':'HP','MCHP':'마이크로칩 테크놀로지','COTY':'코티','CCC':'CCC 인텔리전트 솔루션스','DELL':'델 테크놀로지스','STM':'ST마이크로일렉트로닉스'
}


def normalize_security_name(name:str)->str:
    n=str(name or '').strip()
    patterns=[r'\s+Common Stock.*$',r'\s+Class [A-Z] Common Stock.*$',r'\s+American Depositary.*$',r'\s+Ordinary Shares.*$',r'\s+ADS.*$']
    for p in patterns:n=re.sub(p,'',n,flags=re.I)
    return n.strip(' ,-')


def korean_name(symbol:str, security_name:str|None=None)->str:
    s=str(symbol or '').upper().strip()
    if s in KO_NAMES:return KO_NAMES[s]
    official=normalize_security_name(security_name or '')
    return official or s
