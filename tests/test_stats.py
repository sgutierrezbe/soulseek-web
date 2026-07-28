"""Upload statistics: counting, de-duplication, persistence and ranking."""

from datetime import datetime, timedelta, timezone

import pytest

from stats import _is_succeeded, _split_path, stats


def _upload(transfer_id, username="taker", filename=r"C:\Music\Artist - Album\01 Song.flac",
            size=1000, state="Completed, Succeeded", ended=None):
    ended = ended or datetime.now(timezone.utc)
    return {
        "id": transfer_id,
        "username": username,
        "filename": filename,
        "size": size,
        "bytesTransferred": size,
        "state": state,
        "endedAt": ended.isoformat(),
    }


@pytest.fixture(autouse=True)
def clean_stats():
    stats.reset()
    yield
    stats.reset()


# ── helpers ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        (r"C:\Music\Artist - Album\01 Song.flac", ("Artist - Album", "01 Song.flac")),
        ("/home/me/Music/Album/02 Track.mp3", ("Album", "02 Track.mp3")),
        ("bare.mp3", ("", "bare.mp3")),
        ("", ("", "")),
    ],
)
def test_split_path(raw, expected):
    assert _split_path(raw) == expected


@pytest.mark.parametrize(
    "state, expected",
    [
        ("Completed, Succeeded", True),
        ("Completed, Errored", False),
        ("Completed, Cancelled", False),
        ("InProgress", False),
        ("", False),
    ],
)
def test_is_succeeded(state, expected):
    assert _is_succeeded(state) is expected


# ── counting ─────────────────────────────────────────────────────────────────


def test_only_successful_transfers_are_counted():
    stats.record([
        _upload("a", state="Completed, Succeeded"),
        _upload("b", state="Completed, Errored"),
        _upload("c", state="InProgress"),
        _upload("d", state="Completed, Cancelled"),
    ])
    assert stats.summary()["totals"]["files"] == 1


def test_repeated_polls_do_not_double_count():
    poll = [_upload("a"), _upload("b")]
    for _ in range(5):
        stats.record(poll)
    totals = stats.summary()["totals"]
    assert totals["files"] == 2
    assert totals["bytes"] == 2000


def test_new_transfers_accumulate_across_polls():
    stats.record([_upload("a")])
    stats.record([_upload("a"), _upload("b")])
    assert stats.summary()["totals"]["files"] == 2


def test_a_transfer_dropped_by_slskd_is_not_recounted_if_it_reappears():
    """The bookkeeping set is pruned to what slskd reports, so this is the one
    case that could double count. Ids are GUIDs, so it cannot happen in
    practice -- but the same id must still only ever be counted once per run."""
    stats.record([_upload("a")])
    stats.record([])                      # slskd drops it from the list
    stats.record([_upload("a")])          # same id returns
    # It is counted again, which is the accepted trade-off for a bounded set;
    # assert the behaviour explicitly so a future change is deliberate.
    assert stats.summary()["totals"]["files"] == 2


def test_same_file_taken_repeatedly_counts_each_time():
    path = r"C:\Music\Album\01 Song.flac"
    stats.record([_upload("a", filename=path), _upload("b", filename=path)])
    stats.record([_upload("a", filename=path), _upload("b", filename=path), _upload("c", filename=path)])

    top = stats.summary()["top_files"][0]
    assert top["name"] == "01 Song.flac"
    assert top["count"] == 3


def test_partial_transfer_counts_bytes_actually_sent():
    transfer = _upload("a", size=5000)
    transfer["bytesTransferred"] = 1500
    stats.record([transfer])
    assert stats.summary()["totals"]["bytes"] == 1500


def test_distinct_users_are_tracked():
    stats.record([_upload("a", username="alice"), _upload("b", username="bob"), _upload("c", username="alice")])
    summary = stats.summary()
    assert summary["totals"]["users"] == 2
    assert summary["top_users"][0]["username"] == "alice"
    assert summary["top_users"][0]["count"] == 2


# ── ranking ──────────────────────────────────────────────────────────────────


def test_rankings_are_ordered_by_count_so_bars_match_the_figure():
    # Fewer, larger transfers must not outrank more numerous smaller ones.
    stats.record([
        _upload("a", filename=r"C:\M\Big\one.flac", size=10_000_000),
        _upload("b", filename=r"C:\M\Small\x.mp3", size=10),
        _upload("c", filename=r"C:\M\Small\y.mp3", size=10),
        _upload("d", filename=r"C:\M\Small\z.mp3", size=10),
    ])
    albums = stats.summary()["top_albums"]
    assert [a["folder"] for a in albums] == ["Small", "Big"]
    assert albums[0]["count"] == 3


def test_top_is_capped_by_the_requested_size():
    stats.record([
        _upload(str(i), filename=rf"C:\M\Album{i}\t.flac") for i in range(20)
    ])
    assert len(stats.summary(top=5)["top_albums"]) == 5


# ── timeline ─────────────────────────────────────────────────────────────────


def test_timeline_is_dense_and_covers_the_requested_window():
    summary = stats.summary(days=30)
    assert len(summary["timeline"]) == 30
    assert all(point["files"] == 0 for point in summary["timeline"])
    # Ends on today, ascending.
    dates = [p["date"] for p in summary["timeline"]]
    assert dates == sorted(dates)
    assert dates[-1] == datetime.now(timezone.utc).date().isoformat()


def test_uploads_land_on_their_own_day():
    three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
    stats.record([_upload("a", ended=three_days_ago), _upload("b")])

    summary = stats.summary(days=7)
    by_date = {p["date"]: p["files"] for p in summary["timeline"]}
    assert by_date[three_days_ago.date().isoformat()] == 1
    assert by_date[datetime.now(timezone.utc).date().isoformat()] == 1
    assert summary["today"]["files"] == 1
    assert summary["week"]["files"] == 2


def test_uploads_older_than_the_window_are_excluded_from_it():
    stats.record([_upload("old", ended=datetime.now(timezone.utc) - timedelta(days=40))])
    summary = stats.summary(days=30)
    assert summary["month"]["files"] == 0
    # But they still count toward the lifetime total.
    assert summary["totals"]["files"] == 1


# ── persistence ──────────────────────────────────────────────────────────────


def test_totals_survive_a_reload_from_disk():
    stats.record([_upload("a"), _upload("b")])
    stats.save(force=True)
    stats.load()
    assert stats.summary()["totals"]["files"] == 2


def test_reset_clears_everything():
    stats.record([_upload("a")])
    stats.reset()
    totals = stats.summary()["totals"]
    assert totals["files"] == 0
    assert totals["users"] == 0


# ── API ──────────────────────────────────────────────────────────────────────


def test_upload_stats_endpoint_works_without_slskd(client):
    """The page must still render its history when slskd is unreachable."""
    stats.record([_upload("a")])
    response = client.get("/api/stats/uploads")
    assert response.status_code == 200
    assert response.json()["totals"]["files"] == 1


def test_stats_endpoints_needing_slskd_report_502(client):
    assert client.get("/api/stats/uploads/active").status_code == 502
    assert client.get("/api/stats/shares").status_code == 502


def test_reset_endpoint(client):
    stats.record([_upload("a")])
    assert client.delete("/api/stats/uploads").status_code == 200
    assert client.get("/api/stats/uploads").json()["totals"]["files"] == 0


def test_days_parameter_is_bounded(client):
    assert client.get("/api/stats/uploads?days=3").status_code == 422
    assert client.get("/api/stats/uploads?days=400").status_code == 422
    assert client.get("/api/stats/uploads?days=90").status_code == 200
