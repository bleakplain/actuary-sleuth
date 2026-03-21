import pytest
from lib.common.result import ProcessResult


def test_success_result():
    result = ProcessResult.success_result({'key': 'value'})
    assert result.success is True
    assert result.get('key') == 'value'
    assert result.get('missing') is None
    assert result.get('missing', 'default') == 'default'


def test_error_result():
    result = ProcessResult.error_result('Test error', 'TestError')
    assert result.success is False
    assert result.error == 'Test error'
    assert result.error_type == 'TestError'


def test_get_or_raise():
    result = ProcessResult.success_result({'key': 'value'})
    assert result.get_or_raise('key') == 'value'


def test_get_or_raise_missing_key():
    result = ProcessResult.success_result({'key': 'value'})
    with pytest.raises(KeyError):
        result.get_or_raise('missing')


def test_from_dict():
    result = ProcessResult.from_dict({'success': True, 'key': 'value'})
    assert result.success is True
    assert result.get('key') == 'value'


def test_from_dict_error():
    result = ProcessResult.from_dict({'success': False, 'error': 'failed', 'error_type': 'TestError'})
    assert result.success is False
    assert result.error == 'failed'


def test_to_dict():
    result = ProcessResult.success_result({'key': 'value'})
    result_dict = result.to_dict()
    assert result_dict == {'success': True, 'key': 'value'}


def test_to_dict_error():
    result = ProcessResult.error_result('failed', 'TestError')
    result_dict = result.to_dict()
    assert result_dict == {'success': False, 'error': 'failed', 'error_type': 'TestError'}
