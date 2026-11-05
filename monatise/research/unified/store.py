"""Local transactional research ledger. No network publication or broker API."""
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from .models import canonical, digest, encode, identity, TERMINAL


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS streams(
          stream TEXT PRIMARY KEY, config_hash TEXT NOT NULL, manifest_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cursors(
          stream TEXT NOT NULL, contract TEXT NOT NULL, cutoff INTEGER NOT NULL, revision INTEGER NOT NULL,
          PRIMARY KEY(stream, contract));
        CREATE TABLE IF NOT EXISTS decisions(
          stream TEXT NOT NULL, contract TEXT NOT NULL, cycle TEXT NOT NULL, input_hash TEXT NOT NULL,
          cutoff INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(stream, contract, cycle));
        CREATE TABLE IF NOT EXISTS market_opportunities(
          opportunity TEXT PRIMARY KEY, contract TEXT NOT NULL, side TEXT NOT NULL, origin TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS opportunities(
          stream TEXT NOT NULL, opportunity TEXT NOT NULL, contract TEXT NOT NULL, status TEXT NOT NULL,
          detected INTEGER NOT NULL, armed INTEGER, triggered INTEGER, primary_pathway TEXT NOT NULL,
          selection TEXT, deadline INTEGER, PRIMARY KEY(stream, opportunity));
        CREATE TABLE IF NOT EXISTS observations(
          stream TEXT NOT NULL, observation TEXT NOT NULL, opportunity TEXT, at_ns INTEGER NOT NULL,
          body TEXT NOT NULL, PRIMARY KEY(stream, observation));
        CREATE TABLE IF NOT EXISTS classifications(
          stream TEXT NOT NULL, opportunity TEXT NOT NULL, pathway TEXT NOT NULL,
          first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL, stage TEXT NOT NULL, first_qualified INTEGER,
          PRIMARY KEY(stream, opportunity, pathway));
        CREATE TABLE IF NOT EXISTS events(
          event TEXT PRIMARY KEY, stream TEXT NOT NULL, opportunity TEXT,
          kind TEXT NOT NULL, at_ns INTEGER NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS selections(
          selection TEXT PRIMARY KEY, stream TEXT NOT NULL, opportunity TEXT NOT NULL,
          selected_ns INTEGER NOT NULL, plan TEXT NOT NULL, plan_hash TEXT NOT NULL,
          UNIQUE(stream, opportunity));
        CREATE TABLE IF NOT EXISTS outbox(
          event TEXT PRIMARY KEY, selection TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
          acknowledged INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS position_events(
          event TEXT PRIMARY KEY, stream TEXT NOT NULL, selection TEXT NOT NULL,
          kind TEXT NOT NULL, at_ns INTEGER NOT NULL, payload TEXT NOT NULL,
          UNIQUE(stream, selection, kind));
        CREATE TRIGGER IF NOT EXISTS immutable_selection_update BEFORE UPDATE ON selections
          BEGIN SELECT RAISE(ABORT, 'immutable_selected_plan'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_selection_delete BEFORE DELETE ON selections
          BEGIN SELECT RAISE(ABORT, 'immutable_selected_plan'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_event_update BEFORE UPDATE ON events
          BEGIN SELECT RAISE(ABORT, 'immutable_event'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_outbox_payload BEFORE UPDATE OF payload,selection,event ON outbox
          BEGIN SELECT RAISE(ABORT, 'immutable_publication_payload'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_position_update BEFORE UPDATE ON position_events
          BEGIN SELECT RAISE(ABORT, 'immutable_position_event'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_position_delete BEFORE DELETE ON position_events
          BEGIN SELECT RAISE(ABORT, 'immutable_position_event'); END;
        ''')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        else:
            self.db.execute('COMMIT')

    def bind(self, stream, config_hash, manifest_hash):
        existing = self.db.execute('SELECT * FROM streams WHERE stream=?', (stream,)).fetchone()
        if existing and (existing['config_hash'], existing['manifest_hash']) != (config_hash, manifest_hash):
            raise Conflict('FROZEN_EXPERIMENT_CONFIGURATION_CONFLICT')
        self.db.execute('INSERT OR IGNORE INTO streams VALUES(?,?,?)', (stream, config_hash, manifest_hash))

    def cached(self, stream, contract, cycle, input_hash):
        row = self.db.execute('SELECT * FROM decisions WHERE stream=? AND contract=? AND cycle=?',
                              (stream, contract, cycle)).fetchone()
        if row:
            if row['input_hash'] != input_hash:
                raise Conflict('CYCLE_INPUT_CONFLICT')
            return json.loads(row['body'])
        return None

    def check_cutoff(self, stream, contract, cutoff):
        row = self.db.execute('SELECT * FROM cursors WHERE stream=? AND contract=?', (stream, contract)).fetchone()
        if row and cutoff <= row['cutoff']:
            raise Conflict('STALE_OR_DUPLICATE_CUTOFF_NEW_CYCLE')

    def record_observation(self, stream, observation, cutoff, qualified=False):
        oid = observation.opportunity_id
        self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?)',
                        (stream, observation.key, oid, cutoff, canonical(observation)))
        if oid is None:
            return
        origin_body = encode(observation.origin)
        origin_body.pop('available_ns')
        origin = canonical(origin_body)
        old = self.db.execute('SELECT * FROM market_opportunities WHERE opportunity=?', (oid,)).fetchone()
        if old and (old['contract'], old['side'], old['origin']) != (observation.origin.contract, observation.side, origin):
            raise Conflict('CANONICAL_EPISODE_COLLISION')
        self.db.execute('INSERT OR IGNORE INTO market_opportunities VALUES(?,?,?,?)',
                        (oid, observation.origin.contract, observation.side, origin))
        prior = self.db.execute('SELECT * FROM opportunities WHERE stream=? AND opportunity=?', (stream, oid)).fetchone()
        if prior is None:
            self.db.execute('INSERT INTO opportunities VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (stream, oid, observation.origin.contract, 'WATCHING', observation.detected_ns,
                             None, None, observation.pathway, None, None))
            prior = self.db.execute('SELECT * FROM opportunities WHERE stream=? AND opportunity=?', (stream, oid)).fetchone()
        self.db.execute('''INSERT INTO classifications VALUES(?,?,?,?,?,?,?)
                          ON CONFLICT(stream,opportunity,pathway) DO UPDATE SET
                          last_seen=excluded.last_seen, stage=excluded.stage,
                          first_qualified=COALESCE(classifications.first_qualified,excluded.first_qualified)''',
                        (stream, oid, observation.pathway, cutoff, cutoff, observation.stage, cutoff if qualified else None))
        for event in observation.events:
            # Event ledger is stream-scoped; market identity inside the payload
            # is stable and shared. No local admission timestamp is backdated.
            self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)',
                            (identity('ledger', stream, event.key), stream, oid, event.kind,
                             event.available_ns, canonical(event)))
        if prior['status'] in TERMINAL:
            return
        rank = {'WATCHING': 0, 'ARMED': 1, 'TRIGGERED': 2}
        new = observation.stage
        if new not in TERMINAL and rank[new] < rank[prior['status']]:
            new = prior['status']
        self.transition(stream, oid, new, cutoff)
        self.db.execute('''UPDATE opportunities SET armed=COALESCE(armed,?),
                           triggered=COALESCE(triggered,?) WHERE stream=? AND opportunity=?''',
                        (observation.armed_ns, observation.trigger.available_ns if observation.trigger else None, stream, oid))

    def touch_cursor(self, stream, contract, at_ns):
        row = self.db.execute('SELECT cutoff FROM cursors WHERE stream=? AND contract=?',(stream,contract)).fetchone()
        if row and at_ns < row['cutoff']:
            raise Conflict('STALE_LIFECYCLE_EVENT')
        self.db.execute("""INSERT INTO cursors VALUES(?,?,?,1) ON CONFLICT(stream,contract)
                           DO UPDATE SET cutoff=excluded.cutoff, revision=cursors.revision+1
                           WHERE cursors.cutoff<excluded.cutoff""",(stream,contract,at_ns))

    def transition(self, stream, oid, status, at_ns):
        if not self.db.in_transaction:
            with self.transaction():
                return self.transition(stream,oid,status,at_ns)
        row = self.db.execute('SELECT status FROM opportunities WHERE stream=? AND opportunity=?', (stream, oid)).fetchone()
        if row is None:
            raise Conflict('UNKNOWN_OPPORTUNITY')
        contract = self.db.execute('SELECT contract FROM opportunities WHERE stream=? AND opportunity=?',(stream,oid)).fetchone()[0]
        cursor = self.db.execute('SELECT cutoff FROM cursors WHERE stream=? AND contract=?',(stream,contract)).fetchone()
        if cursor and at_ns < cursor['cutoff']:
            raise Conflict('STALE_LIFECYCLE_EVENT')
        old = row['status']
        if old == status:
            return
        if old in TERMINAL:
            raise Conflict('TERMINAL_OPPORTUNITY_CANNOT_RESURRECT')
        allowed = {'WATCHING': {'ARMED', 'TRIGGERED'}|TERMINAL,
                   'ARMED': {'TRIGGERED'}|TERMINAL, 'TRIGGERED': TERMINAL}
        if status not in allowed[old]:
            raise Conflict('INVALID_LIFECYCLE_TRANSITION')
        self.touch_cursor(stream,contract,at_ns)
        self.db.execute('UPDATE opportunities SET status=? WHERE stream=? AND opportunity=?', (status, stream, oid))
        body = {'from': old, 'to': status}
        self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)',
                        (identity('lifecycle', stream, oid, old, status, at_ns), stream, oid,
                         'LIFECYCLE', at_ns, canonical(body)))

    def selected(self, stream, oid):
        row = self.db.execute('SELECT * FROM selections WHERE stream=? AND opportunity=?', (stream, oid)).fetchone()
        return dict(row) if row else None

    def classifications(self, stream, oid):
        return [r['pathway'] for r in self.db.execute('SELECT pathway FROM classifications WHERE stream=? AND opportunity=? AND first_qualified IS NOT NULL ORDER BY pathway', (stream, oid))]

    def status(self, stream, oid):
        row = self.db.execute('SELECT status FROM opportunities WHERE stream=? AND opportunity=?', (stream, oid)).fetchone()
        return row['status'] if row else None

    def roll_contract(self, stream, old_contract, new_contract, at_ns):
        if old_contract == new_contract:
            raise Conflict('ROLL_REQUIRES_DIFFERENT_EXACT_CONTRACT')
        with self.transaction():
            self.touch_cursor(stream,old_contract,at_ns)
            self.touch_cursor(stream,new_contract,at_ns)
            for row in self.db.execute('SELECT opportunity,status FROM opportunities WHERE stream=? AND contract=?', (stream,old_contract)).fetchall():
                if row['status'] not in TERMINAL:
                    self.transition(stream,row['opportunity'],'SUPERSEDED',at_ns)
            self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)',
                            (identity('roll',stream,old_contract,new_contract,at_ns),stream,None,
                             'CONTRACT_ROLL',at_ns,canonical({'old':old_contract,'new':new_contract,
                             'position_closed':False,'reason':'REFERENCE_SIGNAL_SUPERSESSION_ONLY'})))

    def exposure_conflict(self, stream, contract, opportunity, cutoff):
        rows = self.db.execute("""SELECT s.selection,s.opportunity,o.deadline FROM selections s
                                  JOIN opportunities o ON o.stream=s.stream AND o.opportunity=s.opportunity
                                  WHERE s.stream=? AND o.contract=? AND s.opportunity<>?""",
                               (stream, contract, opportunity)).fetchall()
        for row in rows:
            kinds = {r[0] for r in self.db.execute('SELECT kind FROM position_events WHERE stream=? AND selection=?', (stream, row['selection']))}
            unresolved = self.db.execute("SELECT payload FROM position_events WHERE stream=? AND selection=? AND kind='UNRESOLVED'", (stream,row['selection'])).fetchone()
            unresolved_closed = bool(unresolved and json.loads(unresolved[0]).get('position_closed'))
            if ('FILL' in kinds and 'OUTCOME' not in kinds and not unresolved_closed) or (not kinds and row['deadline'] and cutoff < row['deadline']):
                return True
        return False

    def selection_completed(self, stream, selection):
        for r in self.db.execute('SELECT kind,payload FROM position_events WHERE stream=? AND selection=?',(stream,selection)):
            if r['kind'] in ('OUTCOME','MISSED_ENTRY') or (r['kind']=='UNRESOLVED' and json.loads(r['payload']).get('position_closed')):
                return True
        return False

    def expire(self, stream, contract, cutoff):
        for row in self.db.execute('SELECT opportunity FROM opportunities WHERE stream=? AND contract=? AND deadline<=? AND status NOT IN (?,?,?)',
                                   (stream, contract, cutoff, *sorted(TERMINAL))).fetchall():
            self.transition(stream, row['opportunity'], 'EXPIRED', cutoff)

    def claim(self, stream, candidate, cutoff, config_hash, snapshot_hash, pathway, *, policy):
        oid = candidate.observation.opportunity_id
        existing = self.selected(stream, oid)
        if existing:
            return existing['selection'], False, json.loads(existing['plan'])
        plan = encode(candidate.plan)
        plan.update(primary_pathway=pathway, classifications=self.classifications(stream, oid),
                    contract_key=candidate.observation.origin.contract,
                    frozen_policy=encode(policy),frozen_policy_hash=policy.hash,
                    selected_at_ns=cutoff, config_hash=config_hash, snapshot_hash=snapshot_hash,
                    management='FULL_EXIT_FIRST_TARGET_FIXED_STOP',
                    modeled_risk_denominator='SELECTION_WORST_PERMITTED_FILL',
                    execution_eligible=False, mode='SHADOW')
        sid = identity('selection-v1', stream, oid)
        self.db.execute('INSERT INTO selections VALUES(?,?,?,?,?,?)', (sid, stream, oid, cutoff, canonical(plan), digest(plan)))
        self.db.execute('UPDATE opportunities SET selection=?, deadline=? WHERE stream=? AND opportunity=?',
                        (sid, candidate.plan.expires_ns, stream, oid))
        event = identity('selection-event-v1', sid)
        self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)', (event, stream, oid, 'SELECTION', cutoff, canonical(plan)))
        self.db.execute('INSERT INTO outbox(event,selection,payload) VALUES(?,?,?)',
                        (identity('local-outbox-v1', sid), sid,
                         canonical({'selection_event_id': sid, 'opportunity_id': oid, 'plan': plan,
                                    'delivery': 'LOCAL_SHADOW_RECORD_ONLY', 'execution_eligible': False})))
        return sid, True, plan

    def commit_decision(self, stream, contract, cycle, input_hash, cutoff, body):
        self.db.execute('INSERT INTO decisions VALUES(?,?,?,?,?,?)',
                        (stream, contract, cycle, input_hash, cutoff, canonical(body)))
        self.db.execute('''INSERT INTO cursors VALUES(?,?,?,1) ON CONFLICT(stream,contract)
                           DO UPDATE SET cutoff=excluded.cutoff,revision=cursors.revision+1''', (stream, contract, cutoff))

    def pending_outbox(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM outbox WHERE acknowledged=0 ORDER BY event')]

    def acknowledge(self, event):
        self.db.execute('UPDATE outbox SET acknowledged=1 WHERE event=?', (event,))

    def position_event(self, stream, selection, kind, at_ns, payload):
        if kind not in ('FILL', 'OUTCOME', 'MISSED_ENTRY', 'UNRESOLVED'):
            raise ValueError('unsupported_shadow_position_event')
        row = self.db.execute('SELECT selected_ns FROM selections WHERE stream=? AND selection=?', (stream, selection)).fetchone()
        if row is None or at_ns < row['selected_ns']:
            raise Conflict('POSITION_EVENT_PRECEDES_SELECTION')
        event = identity('position-event', stream, selection, kind)
        old = self.db.execute('SELECT * FROM position_events WHERE event=?', (event,)).fetchone()
        if old:
            if (old['at_ns'], old['payload']) != (at_ns, canonical(payload)):
                raise Conflict('IMMUTABLE_POSITION_EVENT_CONFLICT')
            return
        self.db.execute('INSERT OR IGNORE INTO position_events VALUES(?,?,?,?,?,?)',
                        (event, stream, selection, kind, at_ns, canonical(payload)))
        saved = self.db.execute('SELECT at_ns,payload FROM position_events WHERE event=?',(event,)).fetchone()
        if saved is None or (saved['at_ns'],saved['payload']) != (at_ns,canonical(payload)):
            raise Conflict('IMMUTABLE_POSITION_EVENT_CONFLICT')
