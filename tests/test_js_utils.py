"""Unit tests for JS utility functions extracted as pure Python logic.

These test the same algorithms that exist in app.js, validating
the business logic without requiring a browser.
"""

import re


def parse_markdown(text):
    """Python port of app.js parseMarkdown() for testability."""
    if not text:
        return ""
    html = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = re.sub(r"```(\w*)\n([\s\S]*?)```", r"<pre><code>\2</code></pre>", html)
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)

    lines = html.split("\n")
    in_table = False
    table_rows = []
    result = []

    for line in lines:
        trimmed = line.strip()
        if trimmed.startswith("|") and trimmed.endswith("|"):
            if re.sub(r"[|\s\-:]", "", trimmed) == "":
                continue
            if not in_table:
                in_table = True
                table_rows = []
            cells = [c.strip() for c in trimmed.split("|")[1:-1]]
            table_rows.append(cells)
        else:
            if in_table:
                result.append(_render_table(table_rows))
                in_table = False
                table_rows = []
            if trimmed:
                result.append(f"<p>{trimmed}</p>")
    if in_table:
        result.append(_render_table(table_rows))
    return "".join(result)


def _render_table(rows):
    if not rows:
        return ""
    html = "<table>"
    html += "<thead><tr>" + "".join(f"<th>{c}</th>" for c in rows[0]) + "</tr></thead>"
    if len(rows) > 1:
        html += "<tbody>" + "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows[1:]
        ) + "</tbody>"
    html += "</table>"
    return html


def format_elapsed(sec):
    """Python port of app.js formatElapsed()."""
    m = sec // 60
    s = sec % 60
    return f"{m}:{s:02d}"


def format_duration(sec):
    """Python port of app.js formatDuration()."""
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}ч {m}м {s}с"
    if m > 0:
        return f"{m}м {s}с"
    return f"{s}с"


class TestParseMarkdown:
    def test_empty_string(self):
        assert parse_markdown("") == ""

    def test_none(self):
        assert parse_markdown(None) == ""

    def test_plain_text(self):
        result = parse_markdown("Hello world")
        assert "<p>Hello world</p>" in result

    def test_bold(self):
        result = parse_markdown("**bold**")
        assert "<strong>bold</strong>" in result

    def test_italic(self):
        result = parse_markdown("*italic*")
        assert "<em>italic</em>" in result

    def test_inline_code(self):
        result = parse_markdown("`code`")
        assert "<code>code</code>" in result

    def test_code_block(self):
        text = "```python\nprint('hello')\n```"
        result = parse_markdown(text)
        assert "<pre><code>" in result
        assert "print" in result

    def test_table(self):
        text = "| Time | Text |\n|------|------|\n| 0:00 | Hello |"
        result = parse_markdown(text)
        assert "<table>" in result
        assert "<th>Time</th>" in result
        assert "<td>Hello</td>" in result

    def test_table_separator_ignored(self):
        text = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = parse_markdown(text)
        assert "<table>" in result
        assert "<td>1</td>" in result

    def test_html_escaped(self):
        result = parse_markdown("<script>alert('x')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_ampersand_escaped(self):
        result = parse_markdown("A & B")
        assert "&amp;" in result

    def test_multiple_paragraphs(self):
        text = "First paragraph\n\nSecond paragraph"
        result = parse_markdown(text)
        assert result.count("<p>") == 2

    def test_mixed_content(self):
        text = "Hello **world**\n\n| A |\n|---|\n| 1 |"
        result = parse_markdown(text)
        assert "<strong>world</strong>" in result
        assert "<table>" in result


class TestFormatElapsed:
    def test_zero(self):
        assert format_elapsed(0) == "0:00"

    def test_seconds(self):
        assert format_elapsed(45) == "0:45"

    def test_minutes(self):
        assert format_elapsed(125) == "2:05"

    def test_hour(self):
        assert format_elapsed(3661) == "61:01"

    def test_padded_seconds(self):
        assert format_elapsed(61) == "1:01"


class TestFormatDuration:
    def test_seconds_only(self):
        assert format_duration(30) == "30с"

    def test_minutes(self):
        assert format_duration(125) == "2м 5с"

    def test_hours(self):
        assert format_duration(3661) == "1ч 1м 1с"

    def test_exact_hour(self):
        assert format_duration(3600) == "1ч 0м 0с"

    def test_zero(self):
        assert format_duration(0) == "0с"
