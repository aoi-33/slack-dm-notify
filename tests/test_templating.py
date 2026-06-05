from app.templating import extract_variables, render


def test_extract_variables_returns_names_in_order():
    assert extract_variables("{service} deploy {status}") == ["service", "status"]


def test_extract_variables_ignores_escaped_braces():
    assert extract_variables("literal {{not_a_var}} {real}") == ["real"]


def test_extract_variables_dedupes():
    assert extract_variables("{a} {a} {b}") == ["a", "b"]


def test_render_fills_placeholders():
    result = render("{service} deploy {status}", {"service": "api", "status": "ok"})
    assert result.text == "api deploy ok"
    assert result.missing == []


def test_render_reports_missing_keys():
    result = render("{service} deploy {status}", {"service": "api"})
    assert result.text == ""
    assert result.missing == ["status"]


def test_render_ignores_extra_keys():
    result = render("hello {name}", {"name": "bob", "extra": "x"})
    assert result.text == "hello bob"
    assert result.missing == []


def test_render_keeps_escaped_braces_literal():
    result = render("use {{braces}} and {name}", {"name": "bob"})
    assert result.text == "use {braces} and bob"
