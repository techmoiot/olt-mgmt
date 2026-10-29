import os
import tempfile

# Base de datos temporal, antes de que se importe la app
os.environ.setdefault("ONU_DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test.db")

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("ONU_SECRET_KEY", Fernet.generate_key().decode())

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state():
    from app.adapters.mock import mock_reset
    from app.db import Base, engine

    mock_reset()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
