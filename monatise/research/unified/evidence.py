"""Causal native bar evidence. No legacy engine or provider connection imports."""
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from threading import RLock
from .models import (Bar, Pivot, Event, Observation, Side, State, WIDTHS,
                     MINUTE, identity)


@dataclass(frozen=True)
class Frame:
    timeframe: str
    bars: tuple[Bar, ...]
    pivots: tuple[Pivot, ...]
    state: State
    reasons: tuple[str, ...] = ()


def _covered(snapshot, a, b):
    return any(c.kind == 'ohlcv-1m' and c.covers(a, b, snapshot.cutoff_ns) for c in snapshot.coverage)


def aggregate(snapshot, timeframe):
    minutes = tuple(sorted((b for b in snapshot.bars if b.timeframe == '1m'), key=lambda b: b.open_ns))
    if len({b.open_ns for b in minutes}) != len(minutes):
        raise ValueError('duplicate_or_revised_minute')
    if timeframe == '1m':
        return minutes
    width = WIDTHS[timeframe]
    groups = {}
    for b in minutes:
        groups.setdefault(b.open_ns//width*width, []).append(b)
    result = []
    for start, rows in sorted(groups.items()):
        end = start+width
        if end > snapshot.cutoff_ns or not snapshot.schedule.contains(start, end):
            continue
        observed = {b.open_ns for b in rows}
        if any(t not in observed and not _covered(snapshot, t, t+MINUTE)
               for t in range(start, end, MINUTE)):
            continue
        result.append(Bar(snapshot.instrument.key, timeframe, start, end,
                          max(end, *(b.available_ns for b in rows)), rows[0].open,
                          max(b.high for b in rows), min(b.low for b in rows), rows[-1].close,
                          sum(b.volume for b in rows), identity('aggregate-source', *(b.source for b in rows)),
                          tuple(sorted({q for b in rows for q in b.quality}))))
    return tuple(result)


def confirmed_pivots(rows, radius):
    out = []
    for i in range(radius, len(rows)-radius):
        b = rows[i]
        neighbours = rows[i-radius:i]+rows[i+1:i+radius+1]
        high = all(b.high > n.high for n in neighbours)
        low = all(b.low < n.low for n in neighbours)
        if high == low:  # Neither, or ambiguous outside bar: no intrabar order claim.
            continue
        out.append(Pivot(b.contract, b.timeframe, 'HIGH' if high else 'LOW',
                         b.high if high else b.low, b.open_ns, rows[i+radius].close_ns,
                         max(x.available_ns for x in rows[i-radius:i+radius+1]),
                         tuple(x.key for x in rows[i-radius:i+radius+1])))
    return tuple(out)


def frame(snapshot, timeframe, radius=2):
    rows = aggregate(snapshot, timeframe)
    # Do not bridge unreviewed gaps/degraded dependencies. A later clean segment
    # can build its own independently confirmed structure; old context is omitted.
    start = 0
    reasons = set()
    for i, b in enumerate(rows):
        if b.quality:
            start = i+1
            reasons.add('OLDER_DEGRADED_DEPENDENCIES_OMITTED')
        if i and rows[i-1].close_ns < b.open_ns:
            for t in range(rows[i-1].close_ns, b.open_ns, MINUTE):
                if snapshot.schedule.contains(t, t+MINUTE) and not _covered(snapshot, t, t+MINUTE):
                    start = i
                    reasons.add('OLDER_UNVERIFIED_GAP_OMITTED')
                    break
    rows = rows[start:][-512:]
    if not rows or snapshot.cutoff_ns-rows[-1].close_ns > WIDTHS[timeframe]:
        return Frame(timeframe, rows, (), State.UNAVAILABLE, tuple(sorted(reasons|{'INSUFFICIENT_OR_STALE_FRAME'})))
    pivots = confirmed_pivots(rows, radius)
    highs = [p for p in pivots if p.kind == 'HIGH']
    lows = [p for p in pivots if p.kind == 'LOW']
    state = State.UNAVAILABLE
    if len(highs) >= 2 and len(lows) >= 2:
        dh, dl = highs[-1].price-highs[-2].price, lows[-1].price-lows[-2].price
        state = State.UP if dh > 0 and dl > 0 else State.DOWN if dh < 0 and dl < 0 else State.NEUTRAL if dh == dl == 0 else State.MIXED
    elif len(rows) >= 2*radius+1 and len({(b.high, b.low) for b in rows[-(2*radius+1):]}) == 1:
        state = State.NEUTRAL
    return Frame(timeframe, rows, pivots, state, tuple(sorted(reasons)))


def build_frames(snapshot, policy):
    return {tf: frame(snapshot, tf, policy.pivot_radius or 2) for tf in WIDTHS}


def structural_breaks(f, tick):
    out = []
    for i, b in enumerate(f.bars):
        if not i:
            continue
        # Reference and protected pivot must already be confirmed before this bar.
        prior = [p for p in f.pivots if p.confirmed_ns <= b.open_ns and p.available_ns <= b.available_ns]
        for side, kind, opposite in ((Side.BUY, 'HIGH', 'LOW'), (Side.SELL, 'LOW', 'HIGH')):
            refs = [p for p in prior if p.kind == kind]
            protected = [p for p in prior if p.kind == opposite]
            if not refs or not protected:
                continue
            ref, guard = refs[-1], protected[-1]
            d = side.sign
            if d*(b.close-ref.price) >= tick and d*(f.bars[i-1].close-ref.price) < tick:
                event = Event('BREAK', b.contract, side, b.close_ns, b.available_ns,
                              ref.key, ref.price, b.key, (guard.key,))
                out.append((i, event, guard))
    return tuple(out)


def displacement(rows, index, side, baseline_bars):
    if index < baseline_bars:
        return False
    b = rows[index]
    preceding = [abs(x.close-x.open) for x in rows[index-baseline_bars:index]]
    # Directional body exceeds the preceding hour's median; close is in the
    # directional half. This is a transparent hypothesis, not a vendor threshold.
    return (side.sign*(b.close-b.open) > 0 and abs(b.close-b.open) > median(preceding)
            and side.sign*(b.close-(b.high+b.low)/2) >= 0)


def continuation_observations(snapshot, policy, frames):
    f = frames['5m']; tick = snapshot.instrument.tick
    breaks = structural_breaks(f, tick)
    out = []
    for index, origin, guard in breaks:
        rows = f.bars
        d = origin.side.sign
        armed_index = next((j for j in range(index, len(rows))
                            if displacement(rows, j, origin.side, policy.baseline_bars or 12)), None)
        trigger = None; stop = None
        if armed_index is not None:
            for b in rows[armed_index+1:]:
                touches = b.low <= origin.level+tick if origin.side == Side.BUY else b.high >= origin.level-tick
                if touches and d*(b.close-origin.level) >= tick:
                    trigger = Event('RETEST', origin.contract, origin.side, b.close_ns,
                                    b.available_ns, origin.reference_id, origin.level, b.key, (origin.key,))
                    stop = b.low if origin.side == Side.BUY else b.high
                    break
        armed = None if armed_index is None else rows[armed_index].available_ns
        stage = 'WATCHING' if armed is None else 'ARMED' if trigger is None else 'TRIGGERED'
        events = (origin,) if trigger is None else (origin, trigger)
        # A later opposing structural break or breach of the original protected
        # pivot ends this episode. A new break has its own stable origin identity.
        invalidated = any(j > index and other.side != origin.side for j, other, _ in breaks)
        invalidated |= any(d*(b.close-guard.price) < -tick for b in rows[index+1:])
        if trigger and stop is not None:
            invalidated |= any((b.low < stop-tick if origin.side == Side.BUY else b.high > stop+tick)
                               for b in rows if b.open_ns >= trigger.at_ns)
        if invalidated:
            stage = 'INVALIDATED'
        elif trigger and snapshot.cutoff_ns >= trigger.available_ns+(policy.trigger_bars or 1)*WIDTHS['5m']:
            stage = 'EXPIRED'
        elif armed is not None and snapshot.cutoff_ns >= snapshot.schedule.closes_after(origin.at_ns-1):
            stage = 'EXPIRED'
        for pathway in ('A', 'B'):
            out.append(Observation(pathway, origin.side, origin, stage,
                                   origin.available_ns, armed, trigger, guard.price, stop, events))
    return tuple(out)


def reversal_observations(snapshot, policy, frames, continuations):
    f = frames['5m']; tick = snapshot.instrument.tick
    out = []
    for i, b in enumerate(f.bars):
        prior = [p for p in f.pivots if p.confirmed_ns <= b.open_ns and p.available_ns <= b.available_ns]
        for side, kind in ((Side.BUY, 'LOW'), (Side.SELL, 'HIGH')):
            refs = [p for p in prior if p.kind == kind]
            if not refs:
                continue
            ref = refs[-1]
            excursion = b.low <= ref.price-tick if side == Side.BUY else b.high >= ref.price+tick
            if not excursion or side.sign*(b.close-ref.price) < tick:
                continue
            sweep = Event('SWEEP_REJECTION', b.contract, side, b.close_ns,
                          b.available_ns, ref.key, ref.price, b.key)
            # Reversal BOS must be on a later bar: OHLC cannot prove sweep/BOS
            # order within one candle. Only shared proven BOS origins are merged.
            later = [o for o in continuations if o.pathway == 'A' and o.side == side
                     and o.origin.at_ns > sweep.at_ns and o.origin.at_ns <= snapshot.schedule.closes_after(sweep.at_ns-1)]
            if not later:
                out.append(Observation('C', side, sweep, 'WATCHING', sweep.available_ns,
                                       None, None, b.low if side == Side.BUY else b.high,
                                       None, (sweep,), ('WAIT_SEPARATE_REVERSAL_BREAK',), False))
                continue
            o = later[0]
            # The intervening move must not have closed through the sweep extreme.
            extreme = b.low if side == Side.BUY else b.high
            if any(side.sign*(x.close-extreme) < -tick for x in f.bars[i+1:] if x.close_ns <= o.origin.at_ns):
                continue
            out.append(Observation('C', side, o.origin, o.stage, sweep.available_ns,
                                   o.armed_ns, o.trigger, extreme, o.stop_level,
                                   (sweep,)+o.events, o.reasons))
    return tuple(out)


def observations(snapshot, policy, frames):
    continuation = continuation_observations(snapshot, policy, frames)
    return continuation+reversal_observations(snapshot, policy, frames, continuation)


def bias(frames):
    h4, h1 = frames['4h'].state, frames['1h'].state
    if State.UNAVAILABLE in (h4, h1):
        return {'value': 'NEUTRAL', 'evidence_status': 'UNAVAILABLE', 'reason': 'MISSING_CONTEXT'}
    directional = {h4, h1}-{State.NEUTRAL, State.MIXED}
    value = 'BULLISH' if directional == {State.UP} else 'BEARISH' if directional == {State.DOWN} else 'NEUTRAL'
    return {'value': value, 'evidence_status': 'OBSERVED', 'h4': h4, 'h1': h1}


class EvidenceCache:
    """One immutable snapshot shared by experiment streams; no supplied flags.

    Frozen input identity is safe for this bounded cache. Different feature
    parameters rebuild evidence. It never caches mutable experiment state.
    """
    def __init__(self):
        self._lock = RLock()
        self._snapshot = None
        self._parameters = None

    def get(self, snapshot, policy):
        with self._lock:
            params = (policy.pivot_radius, policy.baseline_bars, policy.trigger_bars)
            if self._snapshot is not snapshot or self._parameters != params:
                self._snapshot = snapshot
                self._parameters = params
                self._frames = build_frames(snapshot, policy)
                self._observations = observations(snapshot, policy, self._frames)
                self._hash = snapshot.hash
                from .diagnostics import describe
                self._summary = describe(snapshot,self._frames)
            return self._frames, self._observations, self._hash, self._summary
