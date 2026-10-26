import pytest

from app.services import disk

GB = 1024**3


@pytest.fixture
def free_space(monkeypatch):
    """Pins how much room the disk 'has', so a test never depends on the machine it runs on."""

    def set_free(gigabytes: float):
        monkeypatch.setattr(disk.shutil, "disk_usage", lambda path: _Usage(int(gigabytes * GB)))

    return set_free


class _Usage:
    total = 500 * GB

    def __init__(self, free: int):
        self.free = free


def test_health_reports_ok_and_database(client, free_space):
    free_space(200)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": True}


def test_health_says_low_disk_but_stays_a_200(client, free_space):
    # a 200 on purpose: Docker's health check reads the code, and a full disk is no reason to
    # restart the API. A monitor that looks for "status":"ok" is what notices.
    free_space(3)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "low_disk", "db": True}


def test_health_is_a_503_when_the_database_is_gone(client, db, free_space, monkeypatch):
    free_space(200)

    def broken(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(db, "execute", broken)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": False}


def test_the_disk_is_measured_where_the_first_upload_will_make_the_folder(tmp_path, free_space):
    free_space(200)
    not_made_yet = tmp_path / "video" / "later"
    assert disk.free_and_total(not_made_yet) == (200 * GB, 500 * GB)
    assert disk.is_low(not_made_yet) is False
