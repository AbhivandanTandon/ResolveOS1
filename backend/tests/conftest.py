import os
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
os.environ["SEED_DEMO"] = "false"
os.environ["MIGRATE_ON_START"] = "false"
os.environ["ML_ENABLED"] = "false"
os.environ["NVIDIA_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import ml  # noqa: E402

ml.runtime.load()  # ML is disabled for these tests: mark it loaded so warm-up threads never load real models


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


def login(client, email):
    t = client.post("/api/auth/login", json={"email": email}).json()["token"]
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture()
def approver(client):
    return login(client, "anika.rao@example.com")


@pytest.fixture()
def operator(client):
    return login(client, "dev.malhotra@example.com")


@pytest.fixture()
def admin(client):
    return login(client, "sam.iyer@example.com")


@pytest.fixture()
def compliance(client):
    return login(client, "priya.nair@example.com")
