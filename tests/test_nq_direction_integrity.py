"""NQ context and the related FTMO CFD keep direction across every boundary."""
import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

import monatise.adapters.flashalpha as adapter_module
from monatise.adapters.flashalpha import FlashAlphaAdapter
from monatise.application.flashalpha_analysis import flashalpha_directional_bias, build_flashalpha_futures_analysis
from monatise.application.ftmo_master import format_proposal, FTMOMasterError
from monatise.application.ftmo_registry import FTMO_REGISTRY
from monatise.application.market_intelligence import validate_flashalpha_context
from monatise.application.scan_audit import analysis_trace, stamp_analysis
from monatise.application.hierarchy.assets import AssetHierarchyAnalysis
from monatise.application.hierarchy.approval import SIGNALS, CURRENT
from tests.shared_hierarchy_fixtures import persist_proof
from tests.test_flashalpha_adapter import Response
from tests.test_ftmo_master import NOW, service, heartbeat


def nq_context(monkeypatch, direction, net_gex):
    flip = 29800 if direction == 'LONG' else 30200
    raw = {'symbol': 'NQ=F', 'underlying_price': 30000, 'gamma_flip': flip,
           'gamma_flip_status': 'available', 'call_wall': 30400, 'put_wall': 29600,
           'net_gex': net_gex, 'as_of': NOW.isoformat(),
           'data_as_of': {'futures_feed': NOW.isoformat(), 'futures_options_feed': NOW.isoformat()}}
    monkeypatch.setattr(adapter_module, 'urlopen', lambda *args, **kwargs: Response(raw))
    context = FlashAlphaAdapter('test-token').context('nq=f')
    validate_flashalpha_context(context, provider_symbol='NQ=F', now=NOW, maximum_age=timedelta(hours=1))
    return context


async def proposal_for(context, direction):
    control, store = service()
    payload = heartbeat()
    payload['quotes'] = {'US100.cash': {**payload['quotes']['XAUUSD'],
        'bid': '29000', 'ask': '29001', 'tick_size': '0.1', 'point': '0.1',
        'tick_value': '0.1', 'stops_level': '5'}}
    await control.accept_bridge_heartbeat(payload, now=NOW)
    analysis = build_flashalpha_futures_analysis(context)
    assert analysis['direction'] == direction
    # Provider positioning must agree with independently confirmed hierarchy
    # evidence. A context snapshot alone cannot create an index proposal.
    proof = await persist_proof(control, 'US100.cash', NOW, direction=direction,
        entry=str(analysis['entry']), stop=str(analysis['stop_loss']), target=str(analysis['target']))
    trace = analysis_trace(stamp_analysis({**analysis, 'ftmo_symbol': 'US100.cash'}, 'US100.cash'))
    assert trace['direction'] == direction
    proposal = await control.create_signal_proposal(
        signal_id='nq-context-' + direction, symbol='US100.cash', direction=direction,
        analysis_entry=analysis['entry'], analysis_stop=analysis['stop_loss'], analysis_target=analysis['target'],
        source='monatise.futures.scanner', analysis_state=direction, confirmation_status='confirmed',
        analysis_provider='flashalpha', analysis_instrument='NQ=F', evidence_bundle=proof,
        recommended_risk_percent='0.1', now=NOW)
    await control.repository.update_control(kill_switch=False)
    await control.arm('42', now=NOW)
    return control, store, proposal


@pytest.mark.parametrize('direction,bias,side', [('LONG', 'bullish', 'buy'), ('SHORT', 'bearish', 'sell')])
@pytest.mark.parametrize('net_gex', [-100, 100])
def test_nq_to_us100_preserves_direction_through_storage_telegram_and_intent(monkeypatch, direction, bias, side, net_gex):
    context = nq_context(monkeypatch, direction, net_gex)
    # GEX's signed exposure is already in provider convention. It is not a
    # signed trade recommendation, even if its sign differs from price/flip bias.
    assert context['net_gex'] == net_gex
    assert flashalpha_directional_bias(context) == bias
    assert flashalpha_directional_bias(dict(context)) == bias
    instrument = FTMO_REGISTRY.resolve('US100.cash')
    assert (instrument.futures_symbol, instrument.micro_futures_symbol) == ('NQ', 'MNQ')
    async def scenario():
        control, store, proposal = await proposal_for(context, direction)
        assert proposal['side'] == side
        assert proposal['entry'] == ('29001' if side == 'buy' else '29000')
        assert proposal['mapping']['analysis_instrument'] == 'NQ=F'
        assert proposal['mapping']['ftmo_execution_symbol'] == 'US100.cash'
        assert f'Direction: {side.upper()}' in format_proposal(proposal)
        await control.validate_proposal_publication(proposal, now=NOW)
        signal = await store.get(control.repository.SIGNALS, proposal['signal_id'])
        assert signal.value['direction'] == side
        assert (await control.repository.telegram_analysis(proposal['analysis_id']))['decision'] == direction
        assert await control.repository.pending_commands() == ()
        command = await control.approve(proposal['proposal_id'], '42', now=NOW)
        assert command['payload']['side'] == side
        assert Decimal(command['payload']['stop_loss']) < Decimal(command['payload']['entry']) if side == 'buy' else Decimal(command['payload']['stop_loss']) > Decimal(command['payload']['entry'])
        with pytest.raises(FTMOMasterError, match='already'):
            await control.approve(proposal['proposal_id'], '42', now=NOW)
        assert len(await control.repository.pending_commands()) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('status', ['stored_sign_mismatch', 'sensitive_root', 'no_boundary', None])
def test_uncertified_nq_never_generates_direction_from_indicative_number(monkeypatch, status):
    context = nq_context(monkeypatch, 'LONG', -100)
    context['gamma_flip_status'] = status
    assert flashalpha_directional_bias(context) == 'neutral'
    assert build_flashalpha_futures_analysis(context)['direction'] == 'NONE'


def test_corrupted_persisted_direction_blocks_publication_and_approval(monkeypatch):
    context = nq_context(monkeypatch, 'LONG', 100)
    async def scenario():
        control, store, proposal = await proposal_for(context, 'LONG')
        record = await store.get(control.repository.SIGNALS, proposal['signal_id'])
        await store.put(record.namespace, record.key, {**record.value, 'direction': 'sell'}, expected_version=record.version)
        with pytest.raises(FTMOMasterError, match='direction mismatch'):
            await control.validate_proposal_publication(proposal, now=NOW)
        with pytest.raises(FTMOMasterError, match='direction mismatch'):
            await control.approve(proposal['proposal_id'], '42', now=NOW)
        assert await control.repository.pending_commands() == ()
        await control.reject(proposal['proposal_id'], '42')
        assert (await control.repository.proposal(proposal['proposal_id']))[0]['status'] == 'rejected'
    asyncio.run(scenario())


def test_existing_hierarchy_bundle_cannot_be_overwritten_with_opposite_direction(monkeypatch):
    async def scenario():
        control, store = service()
        proof = await persist_proof(control, 'US100.cash', NOW)
        bundle = proof['evidence_bundle']
        record = await store.get(SIGNALS, bundle['bundle_id'])
        async def changed(*args, **kwargs):
            return {'publication_valid': True, 'evidence_bundle': bundle, 'direction': 'SHORT',
                'entry': '2500', 'stop_loss': '2490', 'target': '2520', 'expires_at': record.value['expires_at'],
                'market_price_observation': proof['market_price_observation']}
        hierarchy = AssetHierarchyAnalysis(master=control)
        monkeypatch.setattr(hierarchy, '_analyse', changed)
        result = await hierarchy.analyse(FTMO_REGISTRY.resolve('US100.cash'), now=NOW)
        assert result['reasons'] == ['confirmed_hierarchy_changed']
        assert not result['publication_valid']
        assert (await store.get(SIGNALS, bundle['bundle_id'])).value['direction'] == 'LONG'
        assert (await store.get(CURRENT, 'US100.cash')).value['state'] == 'invalidated'
    asyncio.run(scenario())
