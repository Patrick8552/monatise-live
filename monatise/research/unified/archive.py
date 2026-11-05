"""Read-only, hash-bound DBN archives. No Live/Historical client construction."""
from .models import fixed_decimal
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import struct
from .models import (Instrument, Bar, Trade, Quote, Coverage, Schedule, Snapshot,
                     News, NS, MINUTE, digest, identity, QuoteUnavailable, latest_quote)
from .databento_rules import record_quality, informational_flags, EventOccurrences


def read_json(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>16*1024**2:
        raise ValueError('bounded_regular_manifest_required')
    return json.loads(p.read_text())


def verified_file(path, expected, maximum=128*1024**2):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>maximum:
        raise ValueError('bounded_regular_archive_required')
    if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
        raise ValueError('ARCHIVE_HASH_MISMATCH:'+str(p))
    return p


@dataclass(frozen=True)
class Archive:
    instrument: Instrument
    bars: tuple
    trades: tuple
    quotes: tuple
    coverage: tuple
    schedule: Schedule
    manifest_hash: str
    mode: str
    news: tuple
    news_coverage: bool
    quote_model_ticks: int | None
    native_quote_age_ns: int | None
    definition_available_ns: int
    report: dict
    quote_invalidations: tuple = ()

    def snapshot(self, cutoff):
        if cutoff<self.definition_available_ns:
            raise ValueError('NATIVE_DEFINITION_NOT_YET_AVAILABLE')
        bars=tuple(b for b in self.bars if b.available_ns<=cutoff and b.close_ns<=cutoff)
        trades=tuple(t for t in self.trades if t.available_ns<=cutoff and t.receive_ns<=cutoff)
        quotes=tuple(q for q in self.quotes if q.available_ns<=cutoff and q.receive_ns<=cutoff)
        invalidations=tuple(q for q in self.quote_invalidations if q.available_ns<=cutoff and q.receive_ns<=cutoff)
        native_state=latest_quote(quotes+invalidations)
        if self.quote_model_ticks is not None and self.mode=='HISTORICAL_EVENT_TIME' and bars and not isinstance(native_state,QuoteUnavailable):
            # This is explicitly a research spread assumption, never native L1.
            last=max(bars,key=lambda b:b.close_ns)
            half=self.instrument.tick*Decimal(self.quote_model_ticks)/2
            modeled=Quote(self.instrument.key,last.close_ns,last.available_ns,
                          last.close-half,last.close+half,
                          identity('MODELED_SPREAD_FROM_NATIVE_CLOSE',last.key,self.quote_model_ticks))
            if not quotes or cutoff-quotes[-1].receive_ns>self.native_quote_age_ns:
                quotes=quotes+(modeled,)
        return Snapshot(self.instrument,cutoff,bars,trades,quotes,self.coverage,self.schedule,
                        self.mode,self.manifest_hash,self.news,self.news_coverage,
                        evidence_kind='GENUINE_NATIVE_ARCHIVE_WITH_EXPLICIT_MODELED_SPREAD' if self.quote_model_ticks else 'GENUINE_NATIVE_ARCHIVE',
                        quote_invalidations=invalidations)


@fixed_decimal
def load_archive(manifest_path):
    import databento as db
    import databento_dbn as dn
    from monatise.research.databento.datasets import DatasetCapability
    from monatise.research.databento.live_models import native_definition
    from monatise.research.institutional.models import digest as native_digest
    m=read_json(manifest_path)
    if m.get('mode') not in ('AS_RECORDED','HISTORICAL_EVENT_TIME'):
        raise ValueError('explicit_archive_replay_mode_required')
    mode=m['mode'];latency=m.get('publication_latency_ns')
    if m.get('bar_source_mode','VENDOR_OHLCV') not in ('VENDOR_OHLCV','TRADE_AGGREGATED_WHERE_COVERED'):
        raise ValueError('explicit_supported_bar_source_mode_required')
    if mode=='HISTORICAL_EVENT_TIME' and (type(latency) is not int or latency<0 or not m.get('availability_assumption')):
        raise ValueError('declared_historical_availability_model_required')
    if m.get('quote_model_ticks') is not None and (type(m.get('native_quote_age_ns')) is not int or m['native_quote_age_ns']<=0):
        raise ValueError('modeled_quote_requires_explicit_native_age_budget')
    if mode=='AS_RECORDED' and m.get('quote_model_ticks') is not None:
        raise ValueError('modeled_quote_cannot_claim_as_recorded')
    pre=read_json(verified_file(m['preflight']['path'],m['preflight']['sha256']))
    cap=DatasetCapability('GLBX.MDP3',tuple(pre['schemas']),pre['observed_at_ns'],native_digest(pre))
    pubs={p['publisher_id']:(p['dataset'],p['venue']) for p in pre['publishers']}
    definition_source=m['definition']
    path=verified_file(definition_source['path'],definition_source['sha256'])
    definitions=list(db.DBNStore.from_file(path))
    if not definitions:
        raise ValueError('native_definition_missing')
    contract=native_definition(definitions[0],capability=cap,publishers=pubs,as_of_ns=m['as_of_ns'])
    inst=Instrument(contract.metadata.dataset,contract.metadata.exchange,contract.metadata.publisher_id,
                    contract.metadata.instrument_id,contract.metadata.raw_symbol,contract.metadata.product,
                    contract.metadata.expiration_ns,contract.tick_size,contract.multiplier,
                    contract.metadata.definition_sha256,currency='USD',price_unit=contract.price_unit)
    def signature(c):return c.identity,c.tick_size,c.multiplier,c.metadata.native_terms
    signature0=signature(contract)
    observed=[];coverage=[];counts=Counter();replays=[]
    for source in m.get('history',[]):
        path=verified_file(source['path'],source['sha256'],32*1024**2)
        store=db.DBNStore.from_file(path);md=store.metadata
        rows=list(store)
        if (len(rows)!=source['records'] or not 0<len(rows)<source['request_limit']
                or str(md.dataset)!='GLBX.MDP3' or str(md.schema)!='ohlcv-1m'
                or md.start!=source['start_ns'] or md.end!=source['end_ns']
                or md.limit!=source['request_limit'] or md.partial or md.not_found
                or set(md.symbols)!={inst.symbol}):
            raise ValueError('COMPLETE_HASH_BOUND_HISTORY_RESPONSE_REQUIRED')
        coverage.append(Coverage('ohlcv-1m',source['start_ns'],source['end_ns'],
                                 source['retrieval_ns'] if mode=='AS_RECORDED' else source['start_ns'],source['sha256']))
        for i,row in enumerate(rows):
            if not source['start_ns']<=row.ts_event<source['end_ns']:
                raise ValueError('historical_row_outside_request')
            observed.append(('ohlcv-1m',source['sha256'],i,source['retrieval_ns'],row))
        counts['historical_minutes']+=len(rows)
    for source in m.get('captures',[]):
        rp=verified_file(source['receipt'],source['receipt_sha256'])
        receipt=read_json(rp);folder=rp.parent
        if receipt['errors'] or receipt['symbol']!=inst.symbol:
            raise ValueError('FAILED_OR_WRONG_CONTRACT_CAPTURE')
        native=verified_file(folder/'native.bin',receipt['native_sha256']).read_bytes()
        decoder=dn.DBNDecoder(has_metadata=False,input_version=3)
        offset=0;raw=defaultdict(list);controls=[];actual=Counter()
        while offset<len(native):
            if offset+12>len(native):raise ValueError('TRUNCATED_NATIVE_FRAME')
            at,length=struct.unpack_from('>QI',native,offset);offset+=12
            if not 0<length<=65536 or offset+length>len(native):raise ValueError('INVALID_NATIVE_FRAME')
            data=native[offset:offset+length];offset+=length
            decoded=decoder.write_and_decode(data)
            if len(decoded)!=1 or bytes(decoded[0])!=data:raise ValueError('NATIVE_BYTE_RECONSTRUCTION_FAILED')
            row=decoded[0];actual[type(row).__name__]+=1
            if not receipt['started_ns']<=at<=receipt['ended_ns']:raise ValueError('CAPTURE_AVAILABILITY_OUTSIDE_RECEIPT')
            schema=('definition' if isinstance(row,dn.InstrumentDefMsg) else 'ohlcv-1m' if isinstance(row,dn.OHLCVMsg)
                    else 'trades' if isinstance(row,dn.TradeMsg) else 'mbp-1' if isinstance(row,dn.MBP1Msg) else None)
            if schema:raw[schema].append((at,row))
            if isinstance(row,dn.ErrorMsg):raise ValueError('NATIVE_PROVIDER_ERROR')
            if isinstance(row,dn.SystemMsg):controls.append((at,row))
        if actual!=Counter(receipt['counts']):raise ValueError('SOURCE_RECEIPT_COUNT_MISMATCH')
        expected=set(receipt['archive_sha256'])
        for code in (1,3):
            if any(not any(int(r.code)==code and schema in str(r.msg) for _,r in controls) for schema in expected):
                raise ValueError('SUBSCRIPTION_ACK_OR_REPLAY_INCOMPLETE')
        for schema,sha in receipt['archive_sha256'].items():
            path=verified_file(folder/(schema+'.dbn'),sha)
            if [bytes(x) for x in db.DBNStore.from_file(path)]!=[bytes(r) for _,r in raw[schema]]:
                raise ValueError('ARCHIVE_NATIVE_BYTES_DISAGREE')
            if schema=='definition':
                for _,row in raw[schema]:
                    if signature(native_definition(row,capability=cap,publishers=pubs,as_of_ns=m['as_of_ns']))!=signature0:
                        raise ValueError('NATIVE_CONTRACT_TERMS_CHANGED')
            else:
                for i,(at,row) in enumerate(raw[schema]):observed.append((schema,sha,i,at,row))
        marks=[(at,r) for at,r in controls if int(r.code)==4 and 'ohlcv-1m' in str(r.msg)]
        if marks:
            end=max(r.ts_event for _,r in marks)
            start=(receipt['subscription_starts']['ohlcv-1m']+MINUTE-1)//MINUTE*MINUTE
            available=receipt['ended_ns'] if mode=='AS_RECORDED' else start
            coverage.append(Coverage('ohlcv-1m',start,end,available,receipt['native_sha256']))
        available=max(at for at,r in controls if int(r.code)==3) if mode=='AS_RECORDED' else receipt['subscription_starts']['trades']
        coverage.append(Coverage('trades',receipt['subscription_starts']['trades'],receipt['ended_ns'],available,receipt['native_sha256']))
        coverage.append(Coverage('mbp-1',receipt['subscription_starts']['mbp-1'],receipt['ended_ns'],available,receipt['native_sha256']))
        replays.append({'capture':str(folder),'counts':dict(actual),'replay_completed':sorted(expected)})
        counts.update(actual)
    bars={};trades={};quotes={};invalidations={};occurrences=EventOccurrences();overlap=0;bad_quotes=0;quality_counts=Counter();info_counts=Counter();last_index={}
    source_admissions={};aliases=[];duplicate_counts=Counter()

    def retain(collection,key,value,at,schema):
        old=collection.get(key)
        admission_key=(schema,key)
        if old is None:
            collection[key]=value;source_admissions[admission_key]=at
            return
        duplicate_counts[schema]+=1
        aliases.append({'schema':schema,'exchange_event_hash':digest(key),
            'first_source':old.source,'other_source':value.source,
            'first_receive_ns':old.receive_ns,'other_receive_ns':value.receive_ns,
            'first_available_ns':old.available_ns,'other_available_ns':value.available_ns,
            'first_flags':old.raw_flags,'other_flags':value.raw_flags,
            'selection_rule':'EARLIEST_ACTUAL_CAPTURE_ADMISSION_NOT_EARLIEST_RECONSTRUCTED_RECEIVE'})
        quality=tuple(sorted(set(old.quality+value.quality)))
        if (at,value.source)<(source_admissions[admission_key],old.source):
            collection[key]=replace(value,quality=quality);source_admissions[admission_key]=at
        else:collection[key]=replace(old,quality=quality)
    for schema,sha,ordinal,at,row in observed:
        if (row.instrument_id,row.publisher_id)!=(inst.instrument_id,inst.publisher_id):
            raise ValueError('EXACT_NATIVE_IDENTITY_MISMATCH')
        source=sha+':'+str(ordinal)
        index=row.ts_event if schema=='ohlcv-1m' else row.ts_recv
        if index<last_index.get((sha,schema),0):
            raise ValueError('SOURCE_NATIVE_ORDER_REQUIRES_REVIEW')
        last_index[(sha,schema)]=index
        if schema=='ohlcv-1m':
            prices=tuple(Decimal(x)/NS for x in (row.open,row.high,row.low,row.close))
            if any(x%inst.tick for x in prices):raise ValueError('NATIVE_PRICE_OFF_TICK')
            day=datetime.fromtimestamp(row.ts_event/NS,timezone.utc).date().isoformat()
            quality=('PROVIDER_DEGRADED_DATE_EX_POST_SCREEN',) if day in m.get('degraded_dates',[]) else ()
            available=at if mode=='AS_RECORDED' else row.ts_event+MINUTE+latency
            if available<row.ts_event+MINUTE:
                raise ValueError('CANDLE_AVAILABLE_BEFORE_CLOSE')
            b=Bar(inst.key,'1m',row.ts_event,row.ts_event+MINUTE,available,*prices,row.volume,source,quality)
            old=bars.get(b.open_ns)
            if old:
                if (old.open,old.high,old.low,old.close,old.volume)!=(b.open,b.high,b.low,b.close,b.volume):
                    raise ValueError('OVERLAP_CANDLE_REVISION')
                overlap+=1
                if b.available_ns<old.available_ns:bars[b.open_ns]=b
            else:bars[b.open_ns]=b
        else:
            flags=int(row.flags)
            quality=record_quality(flags)
            quality_counts.update(quality)
            info_counts.update(informational_flags(flags))
            available=at if mode=='AS_RECORDED' else row.ts_recv+latency
            # Replay copies can have different capture-server receive times.
            # Use exchange payload + within-source occurrence, retaining aliases.
            key=occurrences.key(schema,sha,ordinal,row)
            if schema=='trades':
                price=Decimal(row.price)/NS
                if price%inst.tick:raise ValueError('NATIVE_PRICE_OFF_TICK')
                value=Trade(inst.key,row.ts_event,row.ts_recv,available,price,row.size,
                            'BUY' if str(row.side)=='B' else 'SELL' if str(row.side)=='A' else None,source,quality,flags,int(row.sequence),ordinal)
                retain(trades,key,value,at,schema)
            else:
                top=row.levels[0];bid,ask=Decimal(top.bid_px)/NS,Decimal(top.ask_px)/NS
                if (not Decimal(0)<bid<ask or not top.bid_sz or not top.ask_sz
                        or top.bid_px==9223372036854775807 or top.ask_px==9223372036854775807):
                    bad_quotes+=1
                    value=QuoteUnavailable(inst.key,row.ts_recv,available,source,
                        tuple(sorted(set(quality+('NATIVE_BBO_UNAVAILABLE',)))),int(row.sequence),ordinal,flags)
                    retain(invalidations,key,value,at,schema)
                    continue
                if bid%inst.tick or ask%inst.tick:raise ValueError('NATIVE_QUOTE_OFF_TICK')
                value=Quote(inst.key,row.ts_recv,available,bid,ask,source,quality,int(row.sequence),ordinal,flags)
                retain(quotes,key,value,at,schema)
    schedule=Schedule(tuple(tuple(v) for v in m['calendar']['intervals']),m['calendar']['reference'],m['calendar']['review_hash'])
    if any(not schedule.contains(b.open_ns,b.close_ns) for b in bars.values()):
        raise ValueError('ARCHIVED_BAR_OUTSIDE_REVIEWED_CALENDAR')
    news=tuple(News(**n) for n in m.get('news',[]))
    report={'manifest':str(Path(manifest_path).resolve()),'manifest_hash':digest(m),'mode':mode,
            'instrument':inst.symbol,'counts':dict(counts),'retained_minutes':len(bars),
            'retained_trades':len(trades),'retained_quotes':len(quotes),'identical_overlap_minutes':overlap,
            'unusable_native_quotes':bad_quotes,'flagged_executions_or_quotes':dict(quality_counts),
            'informational_native_flags':dict(info_counts),'retained_quote_invalidations':len(invalidations),
            'cross_capture_event_duplicates_removed':dict(duplicate_counts),
            'duplicate_source_aliases':aliases,
            'capture_reconciliation':replays,'availability_assumption':m.get('availability_assumption'),
            'publication_latency_ns':latency,'bar_source_mode':'VENDOR_OHLCV',
            'quote_model_ticks':m.get('quote_model_ticks'),'native_quote_age_ns':m.get('native_quote_age_ns'),
            'degraded_dates_ex_post_screen':m.get('degraded_dates',[]),
            'independent_exchange_completeness_certified':False,'paid_downloads':0,'provider_connections':0,
            'news_coverage_complete':bool(m.get('news_coverage')),
            'news_availability_basis':m.get('news_availability_basis'),
            'limitations':m.get('limitations',[])}
    def_available=definition_source['retrieval_ns'] if mode=='AS_RECORDED' else definitions[0].ts_recv
    result=Archive(inst,tuple(sorted(bars.values(),key=lambda b:b.open_ns)),
                   tuple(sorted(trades.values(),key=lambda t:(t.receive_ns,t.available_ns,t.sequence if t.sequence is not None else -1,t.native_ordinal if t.native_ordinal is not None else -1))),
                   tuple(sorted(quotes.values(),key=lambda q:(q.receive_ns,q.available_ns,q.sequence if q.sequence is not None else -1,q.native_ordinal if q.native_ordinal is not None else -1))),
                   tuple(coverage),schedule,digest(m),mode,news,bool(m.get('news_coverage')),
                   m.get('quote_model_ticks'),m.get('native_quote_age_ns'),def_available,report,
                   tuple(sorted(invalidations.values(),key=lambda q:(q.receive_ns,q.available_ns,q.sequence,q.native_ordinal))))
    if m.get('bar_source_mode')=='TRADE_AGGREGATED_WHERE_COVERED':
        from .trade_bars import reconstruct_minutes
        result=reconstruct_minutes(result)
    return result
