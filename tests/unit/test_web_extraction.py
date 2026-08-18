from __future__ import annotations

from config.defaults import DEFAULT_WEB_EXTRACTED_TEXT_MAX_CHARS
from web.extraction import extract_readable_text


def test_extracts_main_content_and_strips_nav_and_scripts():
    html = """
    <html><head><title>Great Article</title><script>evil()</script></head>
    <body>
      <nav>Home | About | Contact</nav>
      <article>
        <h1>Great Article</h1>
        <p>This is the real content of the article, long enough for readability
        to treat it as the main body text rather than boilerplate navigation.</p>
        <p>A second paragraph adds more substantial content so extraction has
        enough signal to correctly identify the article body over the nav bar.</p>
      </article>
      <footer>Copyright 2026</footer>
    </body></html>
    """
    page = extract_readable_text(html, url="https://example.com/article")
    assert "real content of the article" in page.text
    assert "evil()" not in page.text


def test_falls_back_to_plain_strip_when_readability_finds_nothing():
    html = "<html><head><title>Bare page</title></head><body><p>Just some text.</p></body></html>"
    page = extract_readable_text(html, url="https://example.com/bare")
    assert "Just some text." in page.text


def test_truncates_very_long_content():
    long_body = "word " * 50_000
    html = f"<html><body><article><p>{long_body}</p></article></body></html>"
    page = extract_readable_text(html)
    assert page.truncated is True
    assert len(page.text) <= DEFAULT_WEB_EXTRACTED_TEXT_MAX_CHARS


def test_short_content_not_truncated():
    html = "<html><body><article><p>Short text.</p></article></body></html>"
    page = extract_readable_text(html)
    assert page.truncated is False


def test_malformed_html_does_not_raise():
    html = "<html><body><p>Unclosed tag <div> nested wrong </p></body>"
    page = extract_readable_text(html)
    assert isinstance(page.text, str)
