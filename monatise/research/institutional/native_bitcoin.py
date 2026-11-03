"""Reviewed CME BTC outright economics. No spot/perpetual or micro conversion."""
from decimal import Decimal

from .models import number
from .normalize import EconomicConvention, definition

POLICY = 'native-CME-BTC-outright-v1'
REFERENCES = (
    'https://www.cmegroup.com/markets/cryptocurrencies/bitcoin/bitcoin/specs',
    'https://databento.com/docs/examples/instrument-definitions/contract-notional',
)


def validate(record, *, capability, publishers, as_of_ns):
    import databento_dbn as dbn
    if not isinstance(record, dbn.InstrumentDefMsg):
        raise ValueError('native_bitcoin_definition_required')
    if (str(record.asset) != 'BTC' or str(record.exchange) != 'XCME'
            or str(record.currency) != 'USD' or str(record.unit_of_measure) != 'IPNT'
            or str(record.instrument_class) != 'F' or str(record.security_type) != 'FUT'
            or record.leg_count != 0 or str(record.user_defined_instrument) != 'N'
            or record.main_fraction != 255 or str(record.security_update_action) not in {'A', 'M'}):
        raise ValueError('native_bitcoin_outright_units_required')
    scale = Decimal(10**9)
    tick = number(record.min_price_increment, positive=True) / scale
    quantity = number(record.unit_of_measure_qty, positive=True) / scale
    display = number(record.display_factor, positive=True) / scale
    tick_amount = number(record.min_price_increment_amount, positive=True) / scale
    if tick != 5 or quantity != 5 or tick_amount / display != 25:
        raise ValueError('native_bitcoin_economic_contradiction')
    # DBN market prices already express USD per bitcoin. display_factor only
    # participates in checking the native tick amount, never in price rescaling.
    return definition(record, capability=capability, publishers=publishers, as_of_ns=as_of_ns,
        convention=EconomicConvention('BTC', tick, quantity, 'USD_PER_BITCOIN', POLICY))
