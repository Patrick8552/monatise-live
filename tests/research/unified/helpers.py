from dataclasses import replace
from decimal import Decimal as D
from monatise.research.unified.models import *
from monatise.research.unified.evidence import Frame
from monatise.research.unified.policy import exploratory_policy

NOW = 1_800_000_000_000_000_000//WIDTHS['5m']*WIDTHS['5m']


def fixture(side=Side.BUY, *, stage='TRIGGERED', pathway='A', neutral_m15=False):
    inst = Instrument('GLBX.MDP3', 'XCEC', 1, 41271, 'GCZ6', 'GC', NOW+1000*WIDTHS['4h'], D('.1'), D(100), 'a'*64)
    mirror = (lambda x: D(x)) if side == Side.BUY else (lambda x: D(200)-D(x))
    def bar(tf, opened, closed, values, volume=100):
        vals = [mirror(x) for x in values]
        return Bar(inst.key, tf, opened, closed, closed, vals[0], max(vals), min(vals), vals[-1], volume, identity('fixture-bar', tf, opened))
    trigbar = bar('5m', NOW-WIDTHS['5m'], NOW, [100, 102, 98, 101])
    base = tuple(bar('5m', NOW-(14-i)*WIDTHS['5m'], NOW-(13-i)*WIDTHS['5m'], [99, 100, 98, '99.5'], 50) for i in range(12))
    m1 = bar('1m', NOW-MINUTE, NOW, [100, 102, 98, 101])
    target = Pivot(inst.key, '4h', 'HIGH' if side == Side.BUY else 'LOW', mirror(110), NOW-5*WIDTHS['4h'], NOW-4*WIDTHS['4h'], NOW-4*WIDTHS['4h'], ('fixture-proof',))
    expected = State.UP if side == Side.BUY else State.DOWN
    frames = {tf: Frame(tf, (m1,) if tf == '1m' else base+(trigbar,), (target,), State.NEUTRAL if tf == '15m' and neutral_m15 else expected) for tf in WIDTHS}
    q = Quote(inst.key, NOW, NOW, D('101') if side == Side.BUY else D('98.9'), D('101.1') if side == Side.BUY else D('99'), 'engineering-quote')
    schedule = Schedule(((NOW-10*WIDTHS['4h'], NOW+WIDTHS['4h']),), 'ENGINEERING_CALENDAR', 'c'*64)
    snap = Snapshot(inst, NOW, (m1,), (), (q,), (), schedule, 'ENGINEERING_FIXTURE', 'd'*64,
                    news_coverage=True, evidence_kind='ENGINEERING_SYNTHETIC')
    root = Event('BREAK', inst.key, side, NOW-3*WIDTHS['5m'], NOW-3*WIDTHS['5m'], 'known-pivot', D(100), 'break-bar', ('protected-pivot',))
    trigger = Event('RETEST', inst.key, side, NOW, NOW, 'known-pivot', D(100), trigbar.key, (root.key,))
    obs = Observation(pathway, side, root, stage, root.available_ns,
                      NOW-2*WIDTHS['5m'] if stage != 'WATCHING' else None,
                      trigger if stage in ('TRIGGERED', 'EXPIRED', 'INVALIDATED') else None,
                      mirror(95), mirror(98) if stage == 'TRIGGERED' else None,
                      (root, trigger) if stage == 'TRIGGERED' else (root,))
    policy = exploratory_policy(rationale_hash='e'*64, volume_mode='EXECUTED_BAR_PARTICIPATION')
    return snap, policy, frames, obs


def later(snapshot, at_ns, *, bid=None, ask=None):
    q = snapshot.quotes[-1]
    q = replace(q, receive_ns=at_ns, available_ns=at_ns,
                bid=q.bid if bid is None else D(bid), ask=q.ask if ask is None else D(ask))
    return replace(snapshot, cutoff_ns=at_ns, quotes=(q,))


def expected_ratio(numerator,denominator):
    from decimal import localcontext
    with localcontext() as ctx:
        ctx.prec=40
        return D(numerator)/D(denominator)
