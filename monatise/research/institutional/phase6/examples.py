"""Explicit engineering examples only, never real spot or options observations."""
from decimal import Decimal
from ..fixtures import contract,quote,NOW_NS
from ..broker_import import BrokerSpecification,BrokerSessions,ImportedBrokerQuote
from ..models import digest
from .basis import BasisPolicy,evaluate,held_out
from .options import BenchmarkLeg,benchmark_scenarios,map_level,american_diagnostics


def basis_pairs(count=8):
    c=contract()
    spec=BrokerSpecification('ENGINEERING_BROKER','ENGINEERING_SERVER','opaque-engineering-account',
        'XAU/USD','XAUUSD','USD','USD_PER_TRYOZ',2,Decimal('.01'),Decimal('.01'),Decimal(100),
        digest('ENGINEERING_SPEC'),NOW_NS-86400*10**9)
    sessions=BrokerSessions(spec.namespace,digest('ENGINEERING_SESSION'),'ENGINEERING_SESSION_REVIEW',
                           ((NOW_NS-3600*10**9,NOW_NS+3600*10**9),))
    fs=dict(start_ns=NOW_NS-3600*10**9,end_ns=NOW_NS+3600*10**9,review_reference='ENGINEERING_CME_SESSION')
    pairs=[]
    for i in range(count):
        t=NOW_NS-(count-i)*10**9
        f=quote(c,receive_ns=t,ordinal=i)
        b=ImportedBrokerQuote(spec,Decimal('2518'),Decimal('2518.2'),t,t,t+1,t+1,
            digest('ENGINEERING_QUOTES'),digest(i),i,'ENGINEERING_SYNTHETIC',sessions.source_sha256)
        pairs.append((f,b))
    return c,pairs,sessions,fs


def basis_example():
    c,pairs,sessions,fs=basis_pairs()
    policy=BasisPolicy('ENGINEERING_POLICY',timing_bound_review_reference='ENGINEERING_FIXED_BOUND')
    report=evaluate(contract=c,futures_quotes=[p[0] for p in pairs],broker_quotes=[p[1] for p in pairs],
        broker_sessions=sessions,futures_session=fs,policy=policy,cutoff_ns=NOW_NS,futures_level='2520')
    validation=held_out(contract=c,futures_quotes=[p[0] for p in pairs],broker_quotes=[p[1] for p in pairs],
        broker_sessions=sessions,futures_session=fs,policy=policy)
    option=contract(option=True)
    mapped=map_level(level_kind='ACTUAL_OPTION_STRIKE',level='2500',underlying_contract=c,basis_report=report,
        observation_ns=NOW_NS-10**9,available_ns=NOW_NS-10**9+1,cutoff_ns=NOW_NS,
        option_expiry_ns=option.metadata.expiration_ns,option_contract=option,
        level_source_sha256=option.metadata.definition_sha256,evidence_kind='ENGINEERING_SYNTHETIC')
    return dict(evidence_kind='ENGINEERING_SYNTHETIC',basis=report,held_out=validation,options_mapping=mapped)


def options_example():
    legs=(BenchmarkLeg('ENGINEERING_CALL','C',2500,30/365,.04,.2,100,100,digest('ENGINEERING_CALL')),
          BenchmarkLeg('ENGINEERING_PUT','P',2600,30/365,.04,.2,100,100,digest('ENGINEERING_PUT')))
    scenarios=[dict(name='ASSUMED_LONG_ALL',signs={l.reference:1 for l in legs},assumption_reference='ENGINEERING_LONG_INVENTORY'),
               dict(name='ASSUMED_LONG_CALL_SHORT_PUT',signs={legs[0].reference:1,legs[1].reference:-1},
                    assumption_reference='ENGINEERING_MIXED_INVENTORY')]
    return dict(benchmark=benchmark_scenarios(legs=legs,price_grid=(2400,2450,2500,2550,2600,2650,2700),scenarios=scenarios),
                american=american_diagnostics(future=2519,strike=2500,years=30/365,rate=.04,volatility=.2,kind='C'))
