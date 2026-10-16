"""Deleted frozen bridge cannot execute, even if an old checkout is supplied."""
import pytest
from monatise.research.institutional.phase8.spot_runner import run
from monatise.research.native_futures.retired import RetiredFuturesWorkflow


def test_deleted_bridge_has_no_subprocess_or_output(tmp_path):
    with pytest.raises(RetiredFuturesWorkflow):run(tmp_path/'input',tmp_path/'out',frozen_checkout=tmp_path)
    assert not (tmp_path/'out').exists()
