import pytest
from unittest.mock import patch, MagicMock
from lib.common.database import find_regulation
from lib.common.exceptions import RecordNotFoundError


@patch('lib.common.database.get_connection')
def test_find_regulation_not_found(mock_get_connection):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None
    mock_get_connection.return_value.__enter__.return_value = mock_conn

    with pytest.raises(RecordNotFoundError):
        find_regulation("nonexistent_article")


@patch('lib.common.database.get_connection')
def test_find_regulation_success(mock_get_connection):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    mock_row = MagicMock()
    mock_row.keys.return_value = ['law_name', 'article_number', 'content']
    mock_row.__getitem__ = lambda self, key: {'law_name': 'Test Law', 'article_number': 'art1', 'content': 'content'}[key]
    mock_cursor.fetchone.return_value = mock_row
    mock_conn.cursor.return_value = mock_cursor
    mock_get_connection.return_value.__enter__.return_value = mock_conn

    result = find_regulation("art1")
    assert result is not None
