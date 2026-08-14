from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    loader=(ROOT/'static'/'lab_dashboard.js').read_text(encoding='utf-8')
    archive=(ROOT/'static'/'lab_research_archive.js').read_text(encoding='utf-8')
    ui=(ROOT/'static'/'priority_challenger_ab.js').read_text(encoding='utf-8')
    css=(ROOT/'static'/'priority_challenger_ab.css').read_text(encoding='utf-8')
    assert 'priority_challenger_ab.js' not in loader
    assert 'priority_challenger_ab.js' in archive
    assert 'priority_challenger_v1_state.json' in ui
    assert 'priority_challenger_v2_state.json' in ui
    assert 'priority_challenger_v3_state.json' in ui
    assert 'V1 / V2 / V3' in ui
    assert 'V1 · BASELINE' in ui and 'V2 · CAPITAL' in ui and 'V3 · CORR DAMP' in ui
    assert '기본 0.75% · 고상관 0.375%' in ui
    assert '메인 추천 순위에는 아직 적용하지 않습니다' in ui
    assert 'NO RETUNE' in ui
    assert '.pcab-grid' in css and '.pcab-card' in css and '.pcab-corr' in css
    print('priority challenger V1/V2/V3 lazy UI PASS')


if __name__=='__main__':main()
