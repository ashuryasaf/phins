"""The production Postgres URL must be able to load a driver.

Railway injects ``postgresql://``. SQLAlchemy 2.1 resolves that scheme to the
``psycopg`` v3 module. ``psycopg2`` does not satisfy the import, and a missing
driver makes the portal fall back to in-memory storage.
"""


def test_psycopg_v3_imports():
    import psycopg

    version = tuple(int(part) for part in psycopg.__version__.split(".")[:2])
    assert version >= (3, 2)


def test_postgresql_psycopg_url_loads_driver():
    from sqlalchemy import create_engine

    engine = create_engine(
        "postgresql+psycopg://phins:phins@127.0.0.1:1/phins",
        connect_args={"connect_timeout": 1},
    )
    try:
        assert engine.dialect.driver == "psycopg"
        assert engine.dialect.dbapi.__name__ == "psycopg"
    finally:
        engine.dispose()
