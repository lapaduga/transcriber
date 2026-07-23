import pytest  # noqa: F401

from server import (
    ALLOWED_EXTENSIONS,
    _format_duration,
    _sanitize_for_tts,
    allowed_file,
    sanitize_filename,
)


class TestSanitizeFilename:
    def test_replaces_angle_brackets(self):
        assert "<" not in sanitize_filename("file<name.mp4")
        assert ">" not in sanitize_filename("file>name.mp4")

    def test_replaces_colon(self):
        assert ":" not in sanitize_filename("file:name.mp4")

    def test_replaces_quotes(self):
        assert '"' not in sanitize_filename('file"name.mp4')

    def test_replaces_pipe(self):
        assert "|" not in sanitize_filename("file|name.mp4")

    def test_replaces_question_mark(self):
        assert "?" not in sanitize_filename("file?name.mp4")

    def test_replaces_asterisk(self):
        assert "*" not in sanitize_filename("file*name.mp4")

    def test_collapses_multiple_dots(self):
        result = sanitize_filename("file...name.mp4")
        assert ".." not in result

    def test_strips_leading_dots(self):
        result = sanitize_filename("...hidden.mp4")
        assert not result.startswith(".")

    def test_strips_trailing_dots(self):
        result = sanitize_filename("file.mp4...")
        assert not result.endswith(".")

    def test_strips_spaces(self):
        result = sanitize_filename("  file.mp4  ")
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_empty_string_returns_default(self):
        assert sanitize_filename("") == "file"

    def test_only_dots_returns_default(self):
        assert sanitize_filename("...") == "file"

    def test_truncates_long_names(self):
        long_name = "a" * 300 + ".mp4"
        result = sanitize_filename(long_name)
        assert len(result) <= 200

    def test_preserves_normal_filename(self):
        assert sanitize_filename("video.mp4") == "video.mp4"

    def test_cyrillic_preserved(self):
        result = sanitize_filename("видео.mp4")
        assert "видео" in result

    def test_backslash_replaced(self):
        assert "\\" not in sanitize_filename("path\\file.mp4")


class TestAllowedFile:
    def test_mp4_allowed(self):
        assert allowed_file("video.mp4") is True

    def test_mp3_allowed(self):
        assert allowed_file("audio.mp3") is True

    def test_wav_allowed(self):
        assert allowed_file("sound.wav") is True

    def test_flac_allowed(self):
        assert allowed_file("music.flac") is True

    def test_avi_allowed(self):
        assert allowed_file("clip.avi") is True

    def test_mov_allowed(self):
        assert allowed_file("video.mov") is True

    def test_mkv_allowed(self):
        assert allowed_file("video.mkv") is True

    def test_webm_allowed(self):
        assert allowed_file("video.webm") is True

    def test_ogg_allowed(self):
        assert allowed_file("audio.ogg") is True

    def test_m4a_allowed(self):
        assert allowed_file("audio.m4a") is True

    def test_aac_allowed(self):
        assert allowed_file("audio.aac") is True

    def test_wma_allowed(self):
        assert allowed_file("audio.wma") is True

    def test_txt_not_allowed(self):
        assert allowed_file("doc.txt") is False

    def test_exe_not_allowed(self):
        assert allowed_file("virus.exe") is False

    def test_case_insensitive(self):
        assert allowed_file("VIDEO.MP4") is True
        assert allowed_file("Audio.WAV") is True

    def test_no_extension_not_allowed(self):
        assert allowed_file("noext") is False

    def test_all_extensions_covered(self):
        for ext in ALLOWED_EXTENSIONS:
            assert allowed_file(f"file{ext}") is True


class TestSanitizeForTts:
    def test_removes_code_blocks(self):
        text = "Hello ```python\ncode\n```world"
        result = _sanitize_for_tts(text)
        assert "code" not in result
        assert "Hello" in result
        assert "world" in result

    def test_removes_inline_code(self):
        result = _sanitize_for_tts("Use `pip install` command")
        assert "pip install" not in result

    def test_removes_bold(self):
        result = _sanitize_for_tts("**bold text**")
        assert result == "bold text"

    def test_removes_italic(self):
        result = _sanitize_for_tts("*italic text*")
        assert result == "italic text"

    def test_removes_double_underline_italic(self):
        result = _sanitize_for_tts("__underline__")
        assert result == "underline"

    def test_removes_single_underline_italic(self):
        result = _sanitize_for_tts("_underline_")
        assert result == "underline"

    def test_removes_strikethrough(self):
        result = _sanitize_for_tts("~~deleted~~")
        assert result == "deleted"

    def test_removes_links(self):
        result = _sanitize_for_tts("[link text](http://example.com)")
        assert "link text" in result
        assert "http://example.com" not in result

    def test_removes_table_rows(self):
        text = "| col1 | col2 |\n|------|------|\n| a | b |"
        result = _sanitize_for_tts(text)
        assert "col1" not in result

    def test_removes_blockquote_markers(self):
        result = _sanitize_for_tts("> quote text")
        assert ">" not in result

    def test_removes_heading_markers(self):
        result = _sanitize_for_tts("# Heading")
        assert "#" not in result

    def test_collapses_whitespace(self):
        result = _sanitize_for_tts("hello    world")
        assert "  " not in result

    def test_strips_result(self):
        result = _sanitize_for_tts("  hello  ")
        assert result == "hello"

    def test_empty_string(self):
        assert _sanitize_for_tts("") == ""

    def test_plain_text_unchanged(self):
        assert _sanitize_for_tts("simple text") == "simple text"

    def test_removes_smile_emoji(self):
        result = _sanitize_for_tts("Привет \U0001f600 world")
        assert "\U0001f600" not in result
        assert "world" in result

    def test_removes_fire_emoji(self):
        result = _sanitize_for_tts("Done \U0001f525")
        assert "\U0001f525" not in result

    def test_removes_clapping_emoji(self):
        result = _sanitize_for_tts("Great job \U0001f44f")
        assert "\U0001f44f" not in result

    def test_removes_heart_emoji(self):
        result = _sanitize_for_tts("I love \u2764 this")
        assert "\u2764" not in result

    def test_keeps_text_with_emojis(self):
        result = _sanitize_for_tts("Hello how are you")
        assert "Hello" in result
        assert "how" in result


class TestFormatDuration:
    def test_seconds_only(self):
        assert _format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert _format_duration(125) == "2m 5s"

    def test_hours_minutes_seconds(self):
        assert _format_duration(3661) == "1h 1m 1s"

    def test_exact_minute(self):
        assert _format_duration(60) == "1m 0s"

    def test_exact_hour(self):
        assert _format_duration(3600) == "1h 0m 0s"

    def test_zero(self):
        assert _format_duration(0) == "0s"

    def test_large_duration(self):
        result = _format_duration(7200)
        assert "2h" in result

    def test_floors_seconds(self):
        result = _format_duration(65.7)
        assert "1m 5s" in result
