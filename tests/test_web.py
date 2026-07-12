"""Tests for the bundled web console (S23).

The console is a static SPA served same-origin by the API app. These tests assert
the shell + assets are served (publicly — the shell holds no secrets, the JS
authenticates each /v1 call), that ``/`` redirects into it, and that
``api.ui_enabled=false`` removes it entirely.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.web import static_dir

from tests.test_api import API_KEY, FakeApplication


def _client(*, ui_enabled=True):
    app_obj = FakeApplication((API_KEY,))
    app_obj.config.api.ui_enabled = ui_enabled
    return TestClient(create_app(app_obj))


def test_static_assets_exist_on_disk():
    d = static_dir()
    assert (d / "index.html").is_file()
    assert (d / "app.js").is_file()
    assert (d / "styles.css").is_file()


def test_ui_index_served_without_auth():
    resp = _client().get("/ui/")
    assert resp.status_code == 200
    assert "Atlas Console" in resp.text
    assert "app.js" in resp.text


def test_ui_assets_served():
    client = _client()
    js = client.get("/ui/app.js")
    assert js.status_code == 200
    assert "/v1/chat" in js.text  # the SPA talks to the real API
    css = client.get("/ui/styles.css")
    assert css.status_code == 200
    assert "--accent" in css.text


def test_root_redirects_to_ui():
    resp = _client().get("/", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers["location"] == "/ui/"


def test_ui_disabled_returns_404_and_no_redirect():
    client = _client(ui_enabled=False)
    assert client.get("/ui/").status_code == 404
    # With the UI off, `/` is not registered either.
    assert client.get("/", follow_redirects=False).status_code == 404


def test_api_still_works_alongside_ui():
    # Mounting the SPA must not shadow the JSON API.
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
