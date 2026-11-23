import pytest

from ingestion import start_spark


@pytest.fixture(scope="session")
def spark():
    session = start_spark()
    yield session
    session.stop()
