import pytest
from lib.common.exceptions import ActuarySleuthException, DatabaseError, RecordNotFoundError, AuditStepException


def test_actuary_sleuth_exception():
    with pytest.raises(ActuarySleuthException):
        raise ActuarySleuthException("Test error")


def test_database_error():
    with pytest.raises(DatabaseError) as exc_info:
        raise DatabaseError("DB error")
    assert isinstance(exc_info.value, ActuarySleuthException)


def test_record_not_found_error():
    with pytest.raises(RecordNotFoundError) as exc_info:
        raise RecordNotFoundError("Not found")
    assert isinstance(exc_info.value, ActuarySleuthException)


def test_audit_step_exception():
    with pytest.raises(AuditStepException) as exc_info:
        raise AuditStepException("Step failed")
    assert isinstance(exc_info.value, ActuarySleuthException)
