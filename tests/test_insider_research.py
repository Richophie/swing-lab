import io
import json
from pathlib import Path
import zipfile

import numpy as np

import insider_data as idata
import insider_research as ir
import strategy_evolution as se
from tests.test_strategy_evolution import _panel


def _archive():
    tsv = lambda rows: '\n'.join('\t'.join(r) for r in rows) + '\n'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('SUBMISSION.tsv', tsv([['ACCESSION_NUMBER', 'FILING_DATE', 'DOCUMENT_TYPE', 'ISSUERTRADINGSYMBOL'],
                                         ['a1', '31-JAN-2024', '4', 'abc'], ['a2', '01-FEB-2024', '4', 'ABC'], ['a3', '01-FEB-2024', '4/A', 'ABC'], ['a4', '02-FEB-2024', '4', 'ZZZ']]))
        z.writestr('REPORTINGOWNER.tsv', tsv([['ACCESSION_NUMBER', 'RPTOWNERCIK', 'RPTOWNER_RELATIONSHIP'], ['a1', '11', 'Director'], ['a2', '22', 'TenPercentOwner'], ['a4', '33', 'Officer']]))
        z.writestr('NONDERIV_TRANS.tsv', tsv([['ACCESSION_NUMBER', 'TRANS_DATE', 'TRANS_CODE', 'TRANS_SHARES', 'TRANS_PRICEPERSHARE', 'TRANS_ACQUIRED_DISP_CD'],
                                             ['a1', '29-JAN-2024', 'P', '1000', '50', 'A'], ['a1', '29-JAN-2024', 'S', '10', '50', 'D'],
                                             ['a2', '30-JAN-2024', 'P', '1000', '50', 'A'], ['a4', '30-JAN-2024', 'P', '1000', '50', 'A']]))
    return zipfile.ZipFile(io.BytesIO(buffer.getvalue()))


def test_only_officer_or_director_purchases_of_our_symbols_are_kept():
    rows = idata.purchases(_archive(), {'ABC'})
    assert rows == [{'symbol': 'ABC', 'filed': '2024-01-31', 'traded': '2024-01-29', 'owner': '11', 'roles': 'Director', 'value_usd': 50000}]
    assert idata.iso('31-JAN-2024') == '2024-01-31' and idata.iso('bad') is None
    from datetime import datetime, timezone
    q = idata.quarters(datetime(2017, 2, 1, tzinfo=timezone.utc))
    assert q[0] == '2016q3' and q[-1] == '2017q1' and len(q) == 3


def test_a_filing_counts_on_the_first_session_on_or_after_it_became_public():
    panel = _panel()
    ctx = se.Context(panel)
    day = panel['dates'][100]
    weekend = str(np.datetime64(panel['dates'][104]) + np.timedelta64(1, 'D'))          # a Saturday: lands on the next session
    buys = [{'symbol': 'S00', 'filed': day, 'owner': 'a', 'value_usd': 60000}, {'symbol': 'S00', 'filed': day, 'owner': 'b', 'value_usd': 50000},
            {'symbol': 'S00', 'filed': weekend, 'owner': 'c', 'value_usd': 10}, {'symbol': 'NOPE', 'filed': day, 'owner': 'x', 'value_usd': 1}]
    value, count = ir.filing_matrices(ctx, buys)
    assert value[100, 0] == 110000 and count[100, 0] == 2 and value[105, 0] == 10 and value.sum() == 110010
    cluster = ir.recent_insiders(ctx, buys)
    assert cluster[100, 0] == 2 and cluster[105, 0] == 3 and cluster[99, 0] == 0


def test_saved_reports_contract():
    data, report = Path('static/insider_buys.json'), Path('static/insider_research.json')
    if data.exists():
        d = json.loads(data.read_text(encoding='utf-8'))
        assert d['rows'] == len(d['buys']) and all(r['value_usd'] > 0 and r['filed'] for r in d['buys'][:500])
    if report.exists():
        d = json.loads(report.read_text(encoding='utf-8'))
        assert d['status'] == 'RESEARCH_ONLY' and set(d['setups']) == set(ir.SETUPS)
        assert set(d['holding_up']) == {k for k, v in d['setups'].items() if v['holds_up']}


if __name__ == '__main__':
    print('run with pytest')
