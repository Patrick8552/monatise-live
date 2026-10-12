"""Exact native index economics; display factors never rescale DBN prices."""
from decimal import Decimal

from .normalize import definition,EconomicConvention
from .models import number

POLICY='native-index-major-currency-reference-v1'
REFERENCES=(
    'https://databento.com/docs/examples/instrument-definitions/contract-notional',
    'https://www.cmegroup.com/education/courses/introduction-to-equity-index-products/discover-equity-index-notional-value-and-price',
)


def validate(record, *, capability,publishers,as_of_ns):
    product=str(record.asset)
    if product not in {'ES','NQ'}:raise ValueError('reviewed_native_index_product_required')
    multiplier=Decimal(50 if product=='ES' else 20)
    tick=Decimal('.25')
    if (str(record.instrument_class)!='F' or str(record.security_type)!='FUT'
            or record.leg_count!=0 or str(record.user_defined_instrument)!='N'
            or str(record.unit_of_measure)!='IPNT' or str(record.currency)!='USD'
            or record.main_fraction!=255 or str(record.security_update_action) not in {'A','M'}):
        raise ValueError('native_outright_index_units_required')
    quantity=number(record.unit_of_measure_qty)/10**9
    display=number(record.display_factor,positive=True)/10**9
    amount=number(record.min_price_increment_amount,positive=True)/10**9
    native_tick=number(record.min_price_increment,positive=True)/10**9
    # Databento publishes tick amount with venue display factor applied. Compare
    # amount/display to USD tick value; DBN market prices already use conventional
    # index points. Never multiply or divide trade/OHLCV prices by display_factor.
    if native_tick!=tick or quantity!=multiplier or amount/display!=tick*multiplier:
        raise ValueError('native_index_currency_convention_contradiction')
    return definition(record,capability=capability,publishers=publishers,as_of_ns=as_of_ns,
        convention=EconomicConvention(product,tick,multiplier,'INDEX_POINT',POLICY))
