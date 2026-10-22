"""Testy pobierania ze stooq bez sieci (odpowiedzi serwera są podstawione)."""
import io

import pytest

from gem import data


class FakeResponse:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status
        self.ok = status == 200


CSV = "Data,Otwarcie,Najwyzszy,Najnizszy,Zamkniecie,Wolumen\n2026-01-02,4,4,4,4.0,0\n2026-01-05,4,4,4,4.1,0\n"
KEY_PAGE = "<!DOCTYPE html><html><body>Aby pobrać dane, podaj apikey ...</body></html>"


@pytest.fixture
def stooq(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(data, "APIKEY_FILE", tmp_path / "stooq_apikey.txt")
    monkeypatch.setattr(data, "_apikey", None)
    monkeypatch.setattr(data, "_asked", False)
    monkeypatch.delenv("STOOQ_APIKEY", raising=False)
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return FakeResponse(CSV if "apikey=ABC123" in url else KEY_PAGE)

    monkeypatch.setattr(data.requests, "get", fake_get)
    return calls


def test_clean_key_accepts_whole_link():
    assert data._clean_key("https://stooq.pl/q/d/l/?s=usdpln&i=d&apikey=ABC123 ") == "ABC123"
    assert data._clean_key("  ABC123\n") == "ABC123"


def test_asks_for_key_saves_it_and_retries(stooq, monkeypatch):
    monkeypatch.setattr(data.sys, "stdin", type("T", (io.StringIO,), {"isatty": lambda self: True})())
    monkeypatch.setattr("builtins.input", lambda prompt="": "https://stooq.pl/q/d/l/?s=usdpln&apikey=ABC123")
    s = data.fetch("usdpln")
    assert s.iloc[-1] == pytest.approx(4.1)
    assert data.APIKEY_FILE.read_text().strip() == "ABC123"
    assert "apikey=ABC123" in stooq[-1]
    # kolejny symbol używa zapisanego klucza bez pytania
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("nie powinno pytać"))
    assert data.fetch("cspx.uk") is not None


def test_without_terminal_explains_how_to_get_key(stooq, monkeypatch):
    monkeypatch.setattr(data.sys, "stdin", io.StringIO())
    with pytest.raises(data.StooqError, match="get_apikey"):
        data.fetch("usdpln")
