import pandas as pd

import earnings_event_audit as audit


class FakeTicker:
    def __init__(self, dates=None, calendar=None):
        self._dates=dates
        self.calendar=calendar or {}
    def get_earnings_dates(self,limit=12):
        if self._dates is None:return pd.DataFrame()
        return pd.DataFrame({'EPS Estimate':[1]*len(self._dates)},index=pd.to_datetime(self._dates,utc=True))


def test_earnings_dates_prefers_future_date():
    t=FakeTicker(['2026-08-01','2026-08-20','2026-11-20'])
    date,status=audit._future_from_earnings_dates(t,'2026-08-13')
    assert status=='ok'
    assert date=='2026-08-20'


def test_calendar_extracts_earnings_date_list():
    t=FakeTicker(calendar={'Earnings Date':[pd.Timestamp('2026-08-21'),pd.Timestamp('2026-08-22')]})
    date,status=audit._future_from_calendar(t,'2026-08-13')
    assert status=='ok'
    assert date=='2026-08-21'


def test_symbol_audit_marks_one_day_source_difference_as_agreement():
    t=FakeTicker(['2026-08-20'],{'Earnings Date':[pd.Timestamp('2026-08-21')]})
    old=audit.yf.Ticker;audit.yf.Ticker=lambda symbol:t
    try:r=audit.audit_symbol('TEST','2026-08-13')
    finally:audit.yf.Ticker=old
    assert r['chosen_next_earnings']=='2026-08-20'
    assert r['sources_agree_within_1d'] is True
    assert r['source_day_diff']==1
    assert r['days_until']==7


def main():
    test_earnings_dates_prefers_future_date()
    test_calendar_extracts_earnings_date_list()
    test_symbol_audit_marks_one_day_source_difference_as_agreement()
    print('earnings event audit PASS')


if __name__=='__main__':main()
