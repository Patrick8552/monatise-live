"""Legacy archive prefix conversion only; canonical delegation deleted."""
from bisect import bisect_right
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from monatise.research.gc_fib.candles import INTERVALS
from monatise.research.gc_fib.worker import snapshot, instant

NS = 10**9


def required_history(timeframe):
    # Historical archive adapter's declared warm-up, not an analytical engine.
    return 51 if timeframe=='4h' else 50



class CutoffAdapter:
    def __init__(self, bars, sessions):
        self.sessions = tuple((s["start_ns"], s["end_ns"]) for s in sessions)
        if not self.sessions or any(a >= b or a % (60*NS) or b % (60*NS) for a,b in self.sessions):
            raise ValueError("reviewed minute sessions required")
        if any(self.sessions[i][1] > self.sessions[i+1][0] for i in range(len(self.sessions)-1)):
            raise ValueError("conflicting sessions")
        keys = [(b.timeframe,b.open_ns) for b in bars]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate_or_revised_bars")
        self.rows = {tf: tuple(sorted((b for b in bars if b.timeframe == tf), key=lambda b:b.open_ns)) for tf in INTERVALS}
        self.bar_hashes = {(b.timeframe,b.open_ns):b.sha256 for b in bars}
        self.clocks = {tf: tuple(b.assumed_available_ns for b in rows) for tf,rows in self.rows.items()}
        # Normalize immutable bars once using the existing GC adapter. Reusing
        # an object is never described as a second independent observation.
        self.normalized = {tf:tuple(snapshot((b,),timeframe=tf,cutoff=b.assumed_available_ns).latest_finalized
                                  for b in rows) for tf,rows in self.rows.items()}
        self.templates = {tf:snapshot(rows[:1],timeframe=tf,cutoff=rows[0].assumed_available_ns)
                          for tf,rows in self.rows.items() if rows}
        self.expected = {}
        for tf,width in INTERVALS.items():
            step = width*NS
            self.expected[tf] = tuple(t for a,b in self.sessions for t in range((a+step-1)//step*step,b,step) if t+step <= b)

    def session(self, cutoff):
        return next(((a,b) for a,b in self.sessions if a <= cutoff < b), None)

    def frames(self, cutoff):
        issues, frames, lineage = [], {}, {}
        session = self.session(cutoff)
        if session is None:
            return {}, ["exchange_closed_or_unreviewed_session"], {}
        for tf,width in INTERVALS.items():
            index = bisect_right(self.clocks[tf],cutoff)
            rows = self.rows[tf][max(0,index-200):index]
            if len(rows) < required_history(tf):
                issues.append(tf+":canonical_history_insufficient"); continue
            expected = self.expected[tf]
            last_expected = bisect_right(expected,cutoff-(width+10)*NS)
            window = expected[bisect_right(expected,rows[0].open_ns-1):last_expected]
            missing = sorted(set(window)-{b.open_ns for b in rows})
            invalid = [b.open_ns for b in rows if not any(a <= b.open_ns < b.close_ns <= z for a,z in self.sessions)]
            if missing: issues.append(tf+":missing_or_no_trade_bar")
            if invalid: issues.append(tf+":bar_outside_session")
            if not last_expected or rows[-1].open_ns != expected[last_expected-1]:
                issues.append(tf+":latest_expected_bar_missing")
            # Required canonical source lifetimes are enforced by Gold._context;
            # this extra transport rule reproduces the two-interval age bound.
            if cutoff-rows[-1].close_ns > 2*width*NS:
                issues.append(tf+":canonical_source_stale")
            normalized = self.normalized[tf][max(0,index-200):index]
            frames[tf] = replace(self.templates[tf],observed_at=instant(cutoff),candles=normalized,
                                 latest_finalized=normalized[-1])
            lineage[tf] = dict(latest_bar_sha256=self.bar_hashes[(tf,rows[-1].open_ns)],
                prefix_sha256=__import__('hashlib').sha256(''.join(self.bar_hashes[(tf,b.open_ns)] for b in rows).encode()).hexdigest(),
                known_at_ns=rows[-1].assumed_available_ns, close_ns=rows[-1].close_ns,
                missing_or_no_trade_opens_ns=missing, outside_session_opens_ns=invalid)
        return frames,issues,lineage
