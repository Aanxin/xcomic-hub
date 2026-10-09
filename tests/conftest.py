"""Pytest configuration for the ManHua Flask app.

`config.py` reads env vars at import time, so we set them BEFORE importing the
`app` package (or anything that imports it). A session-scoped temp DATA_DIR
keeps `create_app`'s `os.makedirs` calls from polluting the real `data/` dir,
and an in-memory SQLite DB keeps tests fast and isolated.
"""

import os
import shutil
import tempfile

import pytest

# --- Set env BEFORE importing app/config ---------------------------------
_TMP_DATA = tempfile.mkdtemp(prefix="manhua_test_")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DATA_DIR"] = _TMP_DATA
# Derived dirs in config.py (COVERS_DIR/PAGES_DIR) follow DATA_DIR; point
# COMICS_DIR at the temp dir explicitly as well to be safe.
os.environ["COMICS_DIR"] = os.path.join(_TMP_DATA, "comics")

# --- Disable the background scheduler before create_app uses it -----------
# `create_app()` instantiates SchedulerService and calls .start(), which would
# spawn daemon threads (and recursively call create_app). No-op it out.
import app.services.scheduler_service as scheduler_service  # noqa: E402

scheduler_service.SchedulerService.start = lambda self: None  # type: ignore[assignment]

from app import create_app, db  # noqa: E402
from app.models import Comic, Collection  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp_data():
    """Remove the session temp DATA_DIR once all tests are done."""
    yield
    shutil.rmtree(_TMP_DATA, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clear_image_cache():
    """每个测试前清空源图片代理磁盘缓存，避免用例间同 URL 串扰。"""
    from config import IMAGE_CACHE_DIR

    shutil.rmtree(IMAGE_CACHE_DIR, ignore_errors=True)
    yield
    shutil.rmtree(IMAGE_CACHE_DIR, ignore_errors=True)


@pytest.fixture()
def app():
    a = create_app()
    a.config["TESTING"] = True
    with a.app_context():
        db.create_all()
        yield a
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_comic(app):
    from datetime import datetime

    def _make(**kwargs):
        defaults = dict(title="comic", author="", file_size=0, rating=0.0)
        defaults.update(kwargs)
        c = Comic(**defaults)
        db.session.add(c)
        db.session.commit()
        return c

    return _make


@pytest.fixture()
def make_collection(app):
    def _make(**kwargs):
        defaults = dict(name="collection")
        defaults.update(kwargs)
        col = Collection(**defaults)
        db.session.add(col)
        db.session.commit()
        return col

    return _make
