"""Normalisering, sortering og caching af pristilbud."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

from .models import Offer, SearchResult


def _clean_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


def normalize_offers(raw: list[dict[str, Any]], vintage: int | None = None) -> list[Offer]:
    """Gør rå tilbud fra modellen pæne: dropper ugyldige, fjerner dubletter,
    beregner pris pr. 75 cl og sorterer billigst først.

    Er en årgang angivet, kommer tilbud med en anden kendt årgang bagerst.
    """
    seen: set[str] = set()
    offers: list[Offer] = []
    for item in raw:
        try:
            price = float(item.get("price_dkk") or 0)
        except (TypeError, ValueError):
            continue
        url = (item.get("url") or "").strip()
        if price <= 0 or not url.startswith(("http://", "https://")):
            continue
        key = _clean_url(url)
        if key in seen:
            continue
        seen.add(key)
        bottle_ml = int(item.get("bottle_ml") or 750) or 750
        offers.append(
            Offer(
                shop=(item.get("shop") or urlsplit(url).netloc).strip(),
                url=url,
                price_dkk=round(price, 2),
                bottle_ml=bottle_ml,
                vintage=item.get("vintage"),
                in_stock=item.get("in_stock"),
                note=item.get("note") or None,
                price_per_75cl=round(price * 750 / bottle_ml, 2),
            )
        )

    def sort_key(o: Offer) -> tuple[int, int, float]:
        wrong_vintage = int(bool(vintage and o.vintage and o.vintage != vintage))
        sold_out = int(o.in_stock is False)
        return (wrong_vintage, sold_out, o.price_per_75cl)

    offers.sort(key=sort_key)
    return offers


def pick_cheapest(offers: list[Offer], vintage: int | None = None) -> Offer | None:
    """Billigste tilbud der er på lager og (hvis kendt) har rette årgang."""
    for o in offers:
        if o.in_stock is False:
            continue
        if vintage and o.vintage and o.vintage != vintage:
            continue
        return o
    return None


class TTLCache:
    """Lille in-memory cache, så samme søgning ikke koster API-kald igen."""

    def __init__(self, ttl_seconds: float, max_items: int = 500) -> None:
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._data: dict[str, tuple[float, SearchResult]] = {}

    @staticmethod
    def key(query: str, vintage: int | None, ean: str | None) -> str:
        return f"{' '.join(query.lower().split())}|{vintage or ''}|{ean or ''}"

    def get(self, key: str) -> SearchResult | None:
        hit = self._data.get(key)
        if not hit:
            return None
        stamp, value = hit
        if time.monotonic() - stamp > self.ttl:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: SearchResult) -> None:
        if len(self._data) >= self.max_items:
            oldest = min(self._data, key=lambda k: self._data[k][0])
            del self._data[oldest]
        self._data[key] = (time.monotonic(), value)
