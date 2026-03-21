#!/usr/bin/env python3


class ActuarySleuthException(Exception):
    pass


class DatabaseError(ActuarySleuthException):
    pass


class RecordNotFoundError(ActuarySleuthException):
    pass


class AuditStepException(ActuarySleuthException):
    pass
