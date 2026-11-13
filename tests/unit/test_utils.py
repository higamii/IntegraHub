import pytest

from integrahub.pagination import Pagination, page_meta
from integrahub.utils import (
    Location,
    content_hash,
    parse_currencies,
    parse_locations,
    parse_repositories,
    slugify,
    utcnow,
)


def test_slugify():
    assert slugify("São Paulo") == "sao-paulo"
    assert slugify("  New   York! ") == "new-york"
    assert slugify("***") == "unknown"


def test_content_hash_ignores_key_order_and_detects_changes():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_utcnow_is_timezone_aware():
    assert utcnow().utcoffset().total_seconds() == 0


def test_parse_locations():
    locations = parse_locations("Sao Paulo:-23.55:-46.63, London:51.51:-0.13")
    assert locations == [Location("Sao Paulo", -23.55, -46.63), Location("London", 51.51, -0.13)]


@pytest.mark.parametrize("raw", ["", "Foo:1", "Foo:abc:2", "X:91:0", "X:0:181", ":1:2"])
def test_parse_locations_rejects_bad_input(raw):
    with pytest.raises(ValueError):
        parse_locations(raw)


def test_parse_repositories():
    assert parse_repositories("fastapi/fastapi, encode/httpx") == [
        "fastapi/fastapi",
        "encode/httpx",
    ]


@pytest.mark.parametrize("raw", ["", "fastapi", "a/b/c", "owner/re po"])
def test_parse_repositories_rejects_bad_input(raw):
    with pytest.raises(ValueError):
        parse_repositories(raw)


def test_parse_currencies():
    assert parse_currencies("brl, eur") == ["BRL", "EUR"]


@pytest.mark.parametrize("raw", ["", "BR", "EURO", "B2N"])
def test_parse_currencies_rejects_bad_input(raw):
    with pytest.raises(ValueError):
        parse_currencies(raw)


def test_page_meta():
    assert page_meta(0, Pagination()) == {"total": 0, "page": 1, "page_size": 20, "pages": 0}
    assert page_meta(41, Pagination(page=2, page_size=20))["pages"] == 3
    assert Pagination(page=3, page_size=20).offset == 40
