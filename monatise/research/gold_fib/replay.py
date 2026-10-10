"""Deterministic local observation-archive replay. No provider/publisher/order imports.

Run: python -m monatise.research.gold_fib.replay INPUT.json OUTPUT_DIRECTORY
Input observation times must be actual archive times; eventual OHLC is insufficient.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from monatise.application.gold_sessions import GoldSessionCalendar
from monatise.application.hierarchy.candles import CandleBoundaryNormalizer
from monatise.application.hierarchy.coordinator import TimeframeSnapshot
from monatise.application.hierarchy.models import Provenance
from monatise.application.take_profit import timestamp
from monatise.core.models import Candle
from monatise.research.gold_fib import SOURCE_COMMIT
from monatise.research.gold_fib.capture import CaptureGoldLayerEvaluator
from monatise.research.gold_fib.f0 import H1FibF0
from monatise.research.gold_fib.models import FrozenRecord, digest


class OfflineReplay:
    def run(self, archive):
        if archive.get('schema') != 'gold-h1-fib-observation-archive-v1':
            raise ValueError('unsupported local archive schema')
        if archive.get('evidence_kind') not in {'ENGINEERING_SYNTHETIC','POINT_IN_TIME_ARCHIVE'}:
            raise ValueError('explicit archive evidence kind required')
        if archive.get('source_commit') != SOURCE_COMMIT:
            raise ValueError('archive canonical source version mismatch')
        self.seeds = []
        self.evaluator = None
        calendar = GoldSessionCalendar.from_manifest(archive['calendar'])
        identity = archive['broker_identity']
        calendar.require_identity(identity['account_id'],identity['server'],identity['symbol'])
        provenance = Provenance('ftmo_mt5_archive', calendar.server, 'XAU/USD',
            archive['source_version'], 'hierarchy-candle-v1')
        normalizer = CandleBoundaryNormalizer()
        evaluator, f0 = CaptureGoldLayerEvaluator(), H1FibF0()
        evaluator.broker_units = archive['broker_units']
        hashes, first_final, rows, records, admissions, seen = {}, {}, {}, [], [], set()
        prior_at = None
        for observation in archive['observations']:
            now = timestamp(observation['at'])
            if prior_at is not None and now <= prior_at:
                raise ValueError('observation times must strictly increase')
            prior_at = now
            snapshots, revised = {}, False
            calendar.require_regular_session(now)
            for tf, raw in observation['candles'].items():
                if tf not in {'4h','1h','15m','5m','1m'}:
                    raise ValueError('unsupported timeframe')
                candles = tuple(Candle(**r) for r in raw)
                if not candles or len(candles)>5000:
                    raise ValueError('bounded nonempty candle history required')
                times = [timestamp(c.timestamp) for c in candles]
                if times != sorted(set(times)) or any(t>now or not calendar.regular_bar(t,tf) for t in times):
                    raise ValueError('inconsistent timestamp/session boundaries')
                normalized = normalizer.normalize_series(candles, symbol='XAU/USD',
                    timeframe=tf, received_at=now, provenance=provenance,
                    previous_hashes=hashes.get(tf,{}))
                previous = hashes.get(tf,{})
                revised |= any(c.candle_id in previous and previous[c.candle_id]!=c.content_hash for c in normalized)
                hashes[tf] = {c.candle_id:c.content_hash for c in normalized}
                known = []
                for c in normalized:
                    key=(c.candle_id,c.content_hash)
                    if c.is_final:
                        first_final.setdefault(key,now)
                        c=replace(c,received_at=first_final[key])
                    known.append(c)
                finalized = [c for c in known if c.is_final]
                rows[tf] = tuple(known)
                if finalized and finalized[-1].open_time == calendar.expected_closed_open(tf,now):
                    snapshots[tf]=TimeframeSnapshot('XAU/USD',tf,now,tuple(known[-evaluator.configuration.candle_limit:]),finalized[-1])
            if observation.get('warmup_only',False):
                continue
            if revised:
                evaluator=CaptureGoldLayerEvaluator()
                evaluator.broker_units=archive['broker_units']
                admissions.append({'at':now,'reason':'CANDLE_REVISION_INVALIDATED_RESEARCH_CHAIN'})
            # All canonical parent snapshots must be available; no cached stale
            # substitute is supplied when an expected bar is absent or forming.
            if set(snapshots) != {'4h','1h','15m','5m','1m'}:
                admissions.append({'at':now,'reason':'REQUIRED_CLOSED_SNAPSHOT_UNAVAILABLE',
                    'missing':sorted({'4h','1h','15m','5m','1m'}-set(snapshots))})
                continue
            try:
                canonical=evaluator.evaluate('XAU/USD',snapshots,evaluated_at=now,macro_degraded=False)
                seed=evaluator.capture_seed(canonical,calendar=calendar,broker_identity=identity,at=now)
                admissions.append({'at':now,'canonical':canonical,'seed_created':seed is not None})
                if seed is not None and seed.association_id not in seen:
                    seen.add(seed.association_id)
                    self.seeds.append(seed)
                    records.append(f0.assess(seed,canonical=canonical))
            except ValueError as exc:
                admissions.append({'at':now,'reason':str(exc)})
        self.evaluator = evaluator
        return FrozenRecord.from_value({'schema':'gold-h1-fib-replay-v1',
            'input_hash':digest(archive),'evidence_kind':archive['evidence_kind'],
            'source_commit':archive['source_commit'], 'records':[r.data for r in records],
            'admissions':admissions, 'seed_rejections':evaluator.seed_rejections})


def write_immutable(path, payload):
    """Unknown/repeated runs cannot overwrite or append duplicate records."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=payload.encode()
    try:
        with path.open('xb') as out:
            out.write(raw)
    except FileExistsError:
        if path.read_bytes()!=raw:
            raise ValueError('immutable artifact conflict:' + str(path))


def main():
    from monatise.research.gold_fib.diagnostics import diagnostics
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.input.stat().st_size>100_000_000:
        raise ValueError('archive too large')
    replay=OfflineReplay().run(json.loads(args.input.read_text()))
    write_immutable(args.output/'replay.json',replay.payload+'\n')
    report=FrozenRecord.from_value(diagnostics(replay.data['records']))
    write_immutable(args.output/'diagnostics.json',report.payload+'\n')
    write_immutable(args.output/'manifest.json',FrozenRecord.from_value({
        'replay_sha256':replay.sha256,'diagnostics_sha256':report.sha256,
        'input_hash':replay.data['input_hash'],'evidence_kind':replay.data['evidence_kind']}).payload+'\n')
    print(f"{len(replay.data['records'])} unique seeds; local shadow artifacts only")


if __name__=='__main__':
    main()
