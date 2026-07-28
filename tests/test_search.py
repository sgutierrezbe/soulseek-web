"""Album grouping, normalisation and ranking."""

import pytest

from routers.search import _build_albums, _deduplicate, extract_year, normalize_folder


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Selected Ambient Works 85-92 [FLAC]", "selected ambient works 85-92"),
        ("Aphex Twin - Drukqs (2001)", "drukqs"),
        ("Untrue [320kbps]", "untrue"),
        ("Kid A (2000) [FLAC 24bit]", "kid a"),
        ("  Homogenic  ", "homogenic"),
    ],
)
def test_normalize_folder_strips_noise(raw, expected):
    assert normalize_folder(raw) == expected


def test_normalize_collapses_format_variants_of_same_album():
    a = normalize_folder("Discovery (2001) [FLAC]")
    b = normalize_folder("Daft Punk - Discovery [MP3 320]")
    assert a == b == "discovery"


@pytest.mark.parametrize(
    "raw, expected",
    [("Kid A (2000)", 2000), ("Album [1997]", 1997), ("No Year Here", None)],
)
def test_extract_year(raw, expected):
    assert extract_year(raw) == expected


def _response(username, folder, ext, count=5, **kwargs):
    return {
        "username": username,
        "uploadSpeed": kwargs.get("speed", 1000),
        "queueLength": 0,
        "hasFreeUploadSlot": kwargs.get("free", True),
        "files": [
            {
                "filename": f"@@share\\Music\\{kwargs.get('artist', 'Artist')}\\{folder}\\{i:02d} Track.{ext}",
                "size": 5_000_000,
                "bitRate": kwargs.get("bitrate", 320),
            }
            for i in range(1, count + 1)
        ],
    }


def test_build_albums_groups_files_by_folder():
    albums = _build_albums([_response("bob", "Drukqs", "flac", count=4)], advanced=False)
    assert len(albums) == 1
    assert albums[0]["track_count"] == 4
    assert albums[0]["extension"] == "FLAC"
    assert albums[0]["lossless"] is True
    assert albums[0]["artist_guess"] == "Artist"


def test_build_albums_skips_single_file_folders_in_normal_mode():
    responses = [_response("bob", "Loose Single", "mp3", count=1)]
    assert _build_albums(responses, advanced=False) == []
    # Advanced mode keeps everything.
    assert len(_build_albums(responses, advanced=True)) == 1


def test_build_albums_marks_mp3_as_lossy():
    album = _build_albums([_response("bob", "Untrue", "mp3")], advanced=False)[0]
    assert album["lossless"] is False
    assert album["extension"] == "MP3"


def test_deduplicate_keeps_higher_bitrate_copy():
    low = _build_albums([_response("a", "Untrue", "mp3", bitrate=128)], advanced=False)
    high = _build_albums([_response("b", "Untrue", "mp3", bitrate=320)], advanced=False)
    result = _deduplicate(low + high)
    assert len(result) == 1
    assert result[0]["bitrate"] == 320


def test_deduplicate_keeps_different_formats_separate():
    flac = _build_albums([_response("a", "Untrue", "flac")], advanced=False)
    mp3 = _build_albums([_response("b", "Untrue", "mp3")], advanced=False)
    result = _deduplicate(flac + mp3)
    assert {album["extension"] for album in result} == {"FLAC", "MP3"}


def test_deduplicate_prefers_free_slot_at_equal_bitrate():
    busy = _build_albums([_response("a", "Drukqs", "mp3", free=False)], advanced=False)
    free = _build_albums([_response("b", "Drukqs", "mp3", free=True)], advanced=False)
    result = _deduplicate(busy + free)
    assert len(result) == 1
    assert result[0]["username"] == "b"


def test_deduplicate_backfills_missing_artist():
    junk = _build_albums(
        [_response("a", "Homogenic", "flac", artist="Music", free=False)], advanced=False
    )
    good = _build_albums(
        [_response("b", "Homogenic", "flac", artist="Bjork", free=False)], advanced=False
    )
    result = _deduplicate(junk + good)
    assert len(result) == 1
    assert result[0]["artist_guess"] == "Bjork"


def test_build_albums_handles_forward_slash_paths():
    response = {
        "username": "unixpeer",
        "uploadSpeed": 500,
        "queueLength": 0,
        "hasFreeUploadSlot": True,
        "files": [
            {"filename": f"/home/music/Bjork/Homogenic/{i} t.flac", "size": 100, "bitRate": 900}
            for i in range(1, 4)
        ],
    }
    album = _build_albums([response], advanced=False)[0]
    assert album["folder_name"] == "Homogenic"
    assert album["artist_guess"] == "Bjork"
