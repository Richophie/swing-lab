from __future__ import annotations

import math


def _f(value):
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def execution_plan_with_atr(plan: dict | None) -> dict:
    """Return a Paper execution plan with ATR reconstructed when necessary.

    The canonical strategy engine already stores entry/stop and the stop distance in
    ATR multiples. Older/public trade-plan payloads did not persist raw ATR itself.
    Reconstructing ATR here keeps the strategy engine untouched while allowing the
    Paper Broker's next-open gap guard to use max(0.75 ATR, 1%) as designed.
    """
    out = dict(plan or {})
    atr = _f(out.get('atr'))
    if atr is not None and atr > 0:
        out['atr'] = atr
        return out

    low = _f(out.get('entry_low', out.get('buy_low')))
    high = _f(out.get('entry_high', out.get('buy_high')))
    stop = _f(out.get('stop'))
    multiple = _f(out.get('stop_atr_multiple'))
    if None not in (low, high, stop, multiple) and multiple > 0:
        entry = (low + high) / 2.0
        inferred = (entry - stop) / multiple
        if inferred > 0 and math.isfinite(inferred):
            out['atr'] = inferred
            out['atr_source'] = 'derived_from_stop_atr_multiple'
            return out

    out['atr'] = None
    return out
