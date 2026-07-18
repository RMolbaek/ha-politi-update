"""Konstanter for POLITI UPDATE-integrationen."""
from __future__ import annotations

DOMAIN = "politi_update"

# Basis-URL for Ritzau-feedsene, som politi.dk distribuerer POLITI UPDATE igennem.
FEED_BASE = "https://via.ritzau.dk/rss/short-messages/latest"

# Visningsnavn -> publisherId. None = feed for alle kredse samlet.
DISTRICTS: dict[str, str | None] = {
    "Alle politikredse": None,
    "Bornholms Politi": "90799",
    "Fyns Politi": "90797",
    "Københavns Politi": "90685",
    "Københavns Vestegns Politi": "90718",
    "Midt- og Vestjyllands Politi": "90687",
    "Midt- og Vestsjællands Politi": "13562881",
    "National enhed for Særlig Kriminalitet": "13562884",
    "Nordjyllands Politi": "13562880",
    "Nordsjællands Politi": "90719",
    "Syd- og Sønderjyllands Politi": "90686",
    "Sydøstjyllands Politi": "90720",
    "Sydsjællands og Lolland-Falsters Politi": "90594",
    "Østjyllands Politi": "90721",
    "Rigspolitiet": "90752",
}

# Feedet har INTET kategori-felt, så kategorierne udledes heuristisk ud fra
# nøgleord i titlen. Rimeligt præcist, men ikke officielt/garanteret.
CATEGORIES: dict[str, list[str]] = {
    "Trafik": [
        "uheld", "færdsel", "trafik", "motorvej", "landevej", "lyskryds",
        "lysskryds", "spærret", "afspærr", "glat", "bilist", "harmonika",
        "vejarbejde", "kø på", "trafikuheld", "påkørt", "påkørsel",
    ],
    "Efterlysning": [
        "efterlys", "savnet", "forsvundet", "hjælp politiet", "genkender",
        "identificer", "sidst set",
    ],
    "Kriminalitet": [
        "skud", "skyder", "skyderi", "overfald", "vold", "røveri", "indbrud",
        "kniv", "drab", "trusler", "narko", "anholdt", "sigtet", "gerningsmand",
    ],
}
# Titler der ikke matcher nogen kategori havner her.
CATEGORY_OTHER = "Øvrige"

CONF_DISTRICTS = "districts"
CONF_CATEGORIES = "categories"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 5  # minutter
MAX_ENTRIES = 25  # hvor mange nyheder der gemmes pr. kreds (før filtrering)


def feed_url(publisher_id: str | None) -> str:
    """Byg feed-URL for en given publisherId."""
    if publisher_id is None:
        return FEED_BASE
    return f"{FEED_BASE}?publisherId={publisher_id}"


def slug_for(publisher_id: str | None) -> str:
    """Stabil nøgle til unique_id."""
    return publisher_id or "alle"


def categorize(title: str) -> list[str]:
    """Udled kategorier fra en titel via nøgleord."""
    text = (title or "").lower()
    matched = [
        name
        for name, keywords in CATEGORIES.items()
        if any(kw in text for kw in keywords)
    ]
    return matched or [CATEGORY_OTHER]
