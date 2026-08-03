import pytest

from src.youtube import (clean_channel_text, guess_format, parse_channel_ref,
                         parse_duration)


def test_guess_format_uses_shorts_playlist_when_available():
    shorts = {"a", "b"}
    assert guess_format(30, shorts, "a") == "shorts"
    assert guess_format(30, shorts, "zzz") == "long"   # 짧아도 목록에 없으면 롱폼
    assert guess_format(150, shorts, "b") == "shorts"  # 60초 초과 쇼츠도 잡는다


def test_guess_format_never_calls_long_video_a_short():
    assert guess_format(600, {"a"}, "a") == "long"     # 3분 초과는 쇼츠일 수 없다


def test_guess_format_falls_back_to_duration_without_playlist():
    assert guess_format(30, None, "a") == "shorts"
    assert guess_format(90, None, "a") == "long"
    assert guess_format(600, None, "a") == "long"


def test_parse_duration():
    assert parse_duration("PT1M30S") == 90
    assert parse_duration("PT1H2M3S") == 3723
    assert parse_duration("PT45S") == 45
    assert parse_duration("garbage") == 0
    assert parse_duration("") == 0


def test_clean_channel_text_strips_browser_copy_artifacts():
    assert clean_channel_text("(20) 워터양 Wateryang - YouTube") == "워터양 Wateryang"
    assert clean_channel_text("(1) 수영에 미치다 - YouTube") == "수영에 미치다"
    assert clean_channel_text("  워터클랜즈  ") == "워터클랜즈"


def test_parse_channel_ref_handle_url():
    assert parse_channel_ref("https://www.youtube.com/@mulchingirl") == ("handle", "mulchingirl")
    assert parse_channel_ref("https://youtube.com/@gogodive/videos") == ("handle", "gogodive")


def test_parse_channel_ref_channel_id_url():
    ref = parse_channel_ref("https://www.youtube.com/channel/UCabc123_XYZ")
    assert ref == ("id", "UCabc123_XYZ")


def test_parse_channel_ref_legacy_url_falls_back_to_search():
    assert parse_channel_ref("https://www.youtube.com/c/SomeName") == ("query", "SomeName")
    assert parse_channel_ref("https://www.youtube.com/user/OldName") == ("query", "OldName")


def test_parse_channel_ref_bare_handle():
    assert parse_channel_ref("@mulchingirl") == ("handle", "mulchingirl")


def test_parse_channel_ref_pasted_title_becomes_query():
    assert parse_channel_ref("(20) 워터양 Wateryang - YouTube") == ("query", "워터양 Wateryang")
    assert parse_channel_ref("(20) Alejandro & Marina 알레한드로와 마리나 - YouTube") == (
        "query", "Alejandro & Marina 알레한드로와 마리나")


def test_parse_channel_ref_plain_name():
    assert parse_channel_ref("워터클랜즈") == ("query", "워터클랜즈")


def test_parse_channel_ref_rejects_empty():
    with pytest.raises(ValueError):
        parse_channel_ref("   ")
