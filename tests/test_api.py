"""HTTP surface: routing, auth, error mapping, range requests, path safety."""

import pytest

TRACK = "Aphex Twin/Selected Ambient Works/01 Xtal.wav"


def test_index_serves_the_app_shell(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'x-data="app()"' in response.text
    # Boot state is inlined to avoid extra round trips before first paint.
    assert "window.__BOOT__" in response.text


def test_health_reports_unreachable_slskd_without_failing(client):
    payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["slskd"] == "unreachable"


def test_static_assets_are_served(client):
    for path in ("/static/css/app.css", "/static/js/app.js", "/manifest.webmanifest", "/sw.js"):
        assert client.get(path).status_code == 200, path


# ── error mapping ────────────────────────────────────────────────────────────


def test_unreachable_slskd_yields_502_not_500(client):
    assert client.post("/api/search/", json={"query": "boards of canada"}).status_code == 502
    assert client.get("/api/downloads/").status_code == 502


def test_empty_query_is_rejected(client):
    assert client.post("/api/search/", json={"query": "   "}).status_code == 400


def test_polling_results_degrades_to_an_error_payload(client):
    """The UI polls this endpoint; it must stay 200 and report the problem."""
    body = client.get("/api/search/does-not-exist").json()
    assert body["albums"] == []
    assert body["error"]


# ── auth ─────────────────────────────────────────────────────────────────────


def test_auth_is_disabled_by_default(client):
    status = client.get("/api/auth/status").json()
    assert status["enabled"] is False
    assert client.get("/api/setup/status").status_code == 200


def test_password_must_be_long_enough(client):
    assert client.post("/api/auth/password", json={"password": "12345"}).status_code == 400


def test_enabling_a_password_locks_the_api_but_not_the_shell(client):
    assert client.post("/api/auth/password", json={"password": "correct-horse"}).status_code == 200

    client.cookies.clear()
    assert client.get("/api/setup/status").status_code == 401
    # The shell must still load so it can render the login screen.
    assert client.get("/").status_code == 200
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/api/auth/status").status_code == 200


def test_login_rejects_a_bad_password_and_accepts_the_right_one(client):
    client.post("/api/auth/password", json={"password": "correct-horse"})
    client.cookies.clear()

    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert client.get("/api/setup/status").status_code == 401

    assert client.post("/api/auth/login", json={"password": "correct-horse"}).status_code == 200
    assert client.get("/api/setup/status").status_code == 200


def test_password_can_be_removed(client):
    client.post("/api/auth/password", json={"password": "correct-horse"})
    assert client.post("/api/auth/password", json={"password": ""}).json()["enabled"] is False
    client.cookies.clear()
    assert client.get("/api/setup/status").status_code == 200


# ── library and streaming ────────────────────────────────────────────────────


def test_library_lists_albums_from_the_music_folder(client):
    albums = client.get("/api/library/albums?refresh=true").json()
    assert len(albums) == 1
    assert albums[0]["album"] == "Selected Ambient Works"
    assert albums[0]["artist"] == "Aphex Twin"
    assert albums[0]["track_count"] == 2
    assert albums[0]["has_cover"] is True


def test_library_tracks_are_ordered_and_tagged(client):
    tracks = client.get("/api/library/tracks", params={"path": "Aphex Twin/Selected Ambient Works"}).json()
    assert [t["filename"] for t in tracks] == ["01 Xtal.wav", "02 Tha.wav"]
    assert tracks[0]["extension"] == "WAV"
    # Duration comes from the audio header even though WAV has no easy tags.
    assert tracks[0]["duration"] == 1


def test_full_audio_response_advertises_range_support(client):
    response = client.get("/api/stream/audio", params={"path": TRACK})
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "audio/wav"


def test_range_request_returns_exactly_the_requested_bytes(client):
    response = client.get(
        "/api/stream/audio", params={"path": TRACK}, headers={"Range": "bytes=100-199"}
    )
    assert response.status_code == 206
    assert len(response.content) == 100
    assert response.headers["content-range"].startswith("bytes 100-199/")


def test_suffix_range_returns_the_tail(client):
    response = client.get(
        "/api/stream/audio", params={"path": TRACK}, headers={"Range": "bytes=-50"}
    )
    assert response.status_code == 206
    assert len(response.content) == 50


def test_unsatisfiable_range_is_416(client):
    response = client.get(
        "/api/stream/audio", params={"path": TRACK}, headers={"Range": "bytes=999999999-"}
    )
    assert response.status_code == 416


def test_download_sets_an_attachment_filename(client):
    response = client.get("/api/stream/download", params={"path": TRACK})
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    # Starlette percent-encodes the name into the RFC 5987 filename* parameter.
    assert disposition.startswith("attachment")
    assert "01%20Xtal.wav" in disposition


# ── path safety ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "../../../../etc/passwd",
        "../../../../Windows/win.ini",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "Aphex Twin/../../../../etc/passwd",
    ],
)
@pytest.mark.parametrize(
    "endpoint", ["/api/stream/audio", "/api/stream/download", "/api/covers/local"]
)
def test_paths_outside_the_music_folder_are_refused(client, endpoint, path):
    response = client.get(endpoint, params={"path": path})
    assert response.status_code in (404, 415), response.status_code


def test_library_tracks_refuses_paths_outside_the_music_folder(client):
    assert client.get("/api/library/tracks", params={"path": "../.."}).status_code == 404


def test_non_audio_files_are_not_streamable(client):
    response = client.get(
        "/api/stream/audio", params={"path": "Aphex Twin/Selected Ambient Works/cover.jpg"}
    )
    assert response.status_code == 415


# ── caching ──────────────────────────────────────────────────────────────────


def test_covers_are_cacheable_and_revalidate_with_an_etag(client):
    response = client.get("/api/covers/folder", params={"folder_name": "Selected Ambient Works"})
    assert response.status_code == 200
    assert "max-age" in response.headers["cache-control"]

    etag = response.headers["etag"]
    cached = client.get(
        "/api/covers/folder",
        params={"folder_name": "Selected Ambient Works"},
        headers={"If-None-Match": etag},
    )
    assert cached.status_code == 304
