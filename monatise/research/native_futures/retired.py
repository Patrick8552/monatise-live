"""Permanent removal of former futures qualification/selector entrypoints."""
class RetiredFuturesWorkflow(ValueError):
    pass


def retired(*args,**kwargs):
    raise RetiredFuturesWorkflow('retired_futures_workflow_use_native_futures_market_information')
