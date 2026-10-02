from app.pricing import TTLCache, normalize_offers, pick_cheapest
from app.models import SearchResult


def offer(shop, price, url=None, **kw):
    return {"shop": shop, "url": url or f"https://{shop}.dk/vin", "price_dkk": price, **kw}


def test_sorts_cheapest_first_and_drops_invalid():
    offers = normalize_offers([
        offer("a", 199),
        offer("b", 149),
        offer("c", 0),
        {"shop": "d", "url": "ftp://x", "price_dkk": 10},
        offer("e", "ikke et tal"),
    ])
    assert [o.shop for o in offers] == ["b", "a"]


def test_dedupes_same_product_url():
    offers = normalize_offers([
        offer("a", 120, url="https://www.shop.dk/vin/"),
        offer("a", 125, url="https://shop.dk/vin"),
    ])
    assert len(offers) == 1


def test_normalizes_to_75cl():
    offers = normalize_offers([
        offer("magnum", 300, bottle_ml=1500),
        offer("normal", 200),
    ])
    assert offers[0].shop == "magnum"
    assert offers[0].price_per_75cl == 150


def test_wrong_vintage_and_sold_out_sorted_last_and_not_cheapest():
    offers = normalize_offers([
        offer("old", 90, vintage=2018),
        offer("soldout", 100, vintage=2020, in_stock=False),
        offer("ok", 130, vintage=2020, in_stock=True),
    ], vintage=2020)
    assert [o.shop for o in offers] == ["ok", "soldout", "old"]
    assert pick_cheapest(offers, 2020).shop == "ok"


def test_cache_roundtrip_and_key_normalization():
    cache = TTLCache(ttl_seconds=60)
    key = cache.key("  Château  Musar ", 2017, None)
    assert key == cache.key("château musar", 2017, None)
    result = SearchResult(query="x", offers=[], cheapest=None)
    cache.set(key, result)
    assert cache.get(key) is result


def test_cache_expires():
    cache = TTLCache(ttl_seconds=-1)
    cache.set("k", SearchResult(query="x", offers=[], cheapest=None))
    assert cache.get("k") is None
