"""Errors raised by the mailing service. `user_message` is safe to show in the UI."""

from __future__ import annotations


class MailingError(Exception):
    """An expected failure. `user_message` never contains URLs, stack traces or secrets."""

    def __init__(self, user_message: str, code: str = "error"):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code


class MailingPermissionError(MailingError):
    def __init__(self, user_message: str = "No tiene permisos para esta acción."):
        super().__init__(user_message, code="forbidden")


class MailingValidationError(MailingError):
    def __init__(self, user_message: str, rejected=None):
        super().__init__(user_message, code="invalid_recipients")
        self.rejected = list(rejected or [])


class MailingBusyError(MailingError):
    def __init__(self, user_message: str = "Ya hay un envío en curso para este cliente. Espere unos segundos."):
        super().__init__(user_message, code="busy")
