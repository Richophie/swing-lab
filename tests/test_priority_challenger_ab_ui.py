from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    loader=(ROOT/'static'/'lab_dashboard.js').read_text(encoding='utf-8')
    ui=(ROOT/'static'/'priority_challenger_ab.js').read_text(encoding='utf-8')
    css=(ROOT/'static'/'priority_challenger_ab.css').read_text(encoding='utf-8')
    assert 'priority_challenger_ab.js' in loader
    assert 'priority_challenger_v1_state.json' in ui
    assert 'priority_challenger_v2_state.json' in ui
    assert '1.00% vs 0.75%' in ui
    assert '포지션 크기만 비교' in ui
    assert 'SAME SIGNALS' in ui
    assert '.pcab-grid' in css and '.pcab-card' in css
    print('priority challenger A/B UI PASS')


if __name__=='__main__':main()
