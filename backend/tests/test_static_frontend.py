from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def create_dist(root: Path) -> Path:
    dist = root / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    (assets / "test.js").write_text("export const value = 1;", encoding="utf-8")
    return dist


def test_frontend_serving_disabled_keeps_api_behavior(monkeypatch) -> None:
    monkeypatch.delenv("SERVE_FRONTEND", raising=False)

    with TestClient(create_app(load_model=False)) as client:
        health = client.get("/api/v1/health")
        page = client.get("/")

    assert health.status_code == 200
    assert page.status_code == 404


def test_serves_index_for_known_and_unknown_frontend_routes(tmp_path, monkeypatch) -> None:
    dist = create_dist(tmp_path)
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(dist))

    with TestClient(create_app(load_model=False)) as client:
        root = client.get("/")
        forward = client.get("/forward")
        reverse = client.get("/reverse")
        nested = client.get("/future/route")

    for response in (root, forward, reverse, nested):
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert '<div id="root"></div>' in response.text


def test_serves_assets_without_api_fallback(tmp_path, monkeypatch) -> None:
    dist = create_dist(tmp_path)
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(dist))

    with TestClient(create_app(load_model=False)) as client:
        asset = client.get("/assets/test.js")
        missing_api = client.get("/api/v1/not-found")

    assert asset.status_code == 200
    assert "javascript" in asset.headers["content-type"]
    assert "export const value" in asset.text
    assert missing_api.status_code == 404
    assert missing_api.headers["content-type"].startswith("application/json")
    assert "<html" not in missing_api.text.lower()


def test_asset_path_traversal_cannot_read_dist_external_file(tmp_path, monkeypatch) -> None:
    dist = create_dist(tmp_path)
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(dist))

    with TestClient(create_app(load_model=False)) as client:
        response = client.get("/assets/%2e%2e/secret.txt")
        missing_asset = client.get("/assets/not-found.js")

    assert response.status_code in {404, 405}
    assert missing_asset.status_code == 404
    assert "secret" not in response.text


def test_missing_dist_does_not_break_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(tmp_path / "missing"))

    with TestClient(create_app(load_model=False)) as client:
        health = client.get("/api/v1/health")
        page = client.get("/")

    assert health.status_code == 200
    assert page.status_code == 404
