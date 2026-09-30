_TRANSIENT_SQLSTATES = {"40001", "40P01"}


def is_transient_database_error(error: BaseException) -> bool:
    """A serialization failure or deadlock anywhere in the cause chain: the transaction rolled
    back and running it again may succeed."""
    current: BaseException | None = error
    while current is not None:
        sqlstate = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if sqlstate in _TRANSIENT_SQLSTATES:
            return True
        current = current.__cause__
    return False
