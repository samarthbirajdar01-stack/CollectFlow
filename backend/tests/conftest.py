import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
_TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="collectflow-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TEST_DIRECTORY.name, 'collectflow.db').as_posix()}"


@pytest.fixture(scope="session", autouse=True)
def dispose_test_database():
    yield
    from database import engine

    engine.dispose()
    _TEST_DIRECTORY.cleanup()


@pytest.fixture(autouse=True)
def isolate_test_database():
    from database import Base, engine
    import models

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
