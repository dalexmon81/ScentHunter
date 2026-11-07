from app.services.catalog_index_status import catalog_indexed_flags


class FakeConnection:
    def __init__(self, indexed):
        self.indexed = set(indexed)
        self.queries = []
        self.closed = False

    def execute(self, query, params):
        self.queries.append((query, params))
        store = params[0]
        return FakeCursor(store in self.indexed)

    def close(self):
        self.closed = True


class FakeCursor:
    def __init__(self, found):
        self.found = found

    def fetchone(self):
        return (1,) if self.found else None


def test_reports_active_url_presence_and_closes_connection():
    connection = FakeConnection({"sabina"})
    result = catalog_indexed_flags(
        ["sabina", "deloox", "", None],
        lambda: connection,
    )

    assert result == {"sabina": True, "deloox": False}
    assert [params for _, params in connection.queries] == [("sabina",), ("deloox",)]
    assert all("store_urls" in query and "active=1" in query for query, _ in connection.queries)
    assert connection.closed is True


def test_missing_database_factory_fails_closed_without_opening_connection():
    assert catalog_indexed_flags(["sabina", "deloox"], None) == {
        "sabina": False,
        "deloox": False,
    }


def test_database_error_fails_closed_and_reports_error():
    errors = []
    connection = FakeConnection(set())

    def broken_execute(query, params):
        raise RuntimeError("database unavailable")

    connection.execute = broken_execute
    result = catalog_indexed_flags(["sabina", "deloox"], lambda: connection, on_error=errors.append)

    assert result == {"sabina": False, "deloox": False}
    assert len(errors) == 1
    assert str(errors[0]) == "database unavailable"
    assert connection.closed is True


def test_empty_store_list_does_not_open_database():
    called = []
    assert catalog_indexed_flags([], lambda: called.append(True)) == {}
    assert called == []
