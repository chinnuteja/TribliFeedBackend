"""Postgres portability helpers use psycopg's cursor API.

python test_postgres_adapter.py
"""
from app.db import _PostgresConnection


class FakeCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def executemany(self, sql, params):
        self.calls.append((sql, params))
        return "bulk-ok"


class FakeConnection:
    def __init__(self):
        self.created_cursor = FakeCursor()

    def cursor(self):
        return self.created_cursor


raw = FakeConnection()
db = _PostgresConnection(raw)
result = db.executemany(
    "INSERT INTO seen_urls (url,source) VALUES (?,?)",
    [("https://example.com/1", "source"), ("https://example.com/2", "source")],
)

assert result == "bulk-ok"
sql, params = raw.created_cursor.calls[0]
assert "VALUES (%s,%s)" in sql
assert len(params) == 2

print("postgres adapter OK")
