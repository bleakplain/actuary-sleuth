import pytest
from datetime import datetime
from lib.common.date_utils import get_current_timestamp


def test_get_current_timestamp():
    result = get_current_timestamp()
    assert isinstance(result, datetime)
    assert (datetime.now() - result).total_seconds() < 1
