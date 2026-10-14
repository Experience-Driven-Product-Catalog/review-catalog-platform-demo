"""Demo adapter: the published snapshot is always read-only."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def database(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        yield connection
    finally:
        connection.close()
