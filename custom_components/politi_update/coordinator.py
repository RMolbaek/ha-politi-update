"""Henter, parser og kategoriserer POLITI UPDATE-feeds."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from time import mktime

import feedparser

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import MAX_ENTRIES, categorize, feed_url

_LOGGER = logging.getLogger(__name__)


class PolitiUpdateCoordinator(DataUpdateCoordinator[dict[str, list[dict]]]):
    """Henter feeds for de valgte kredse på ét sted."""

    def __init__(
        self,
        hass: HomeAssistant,
        districts: dict[str, str | None],
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="POLITI UPDATE",
            update_interval=timedelta(minutes=scan_interval),
        )
        # navn -> publisherId (None = alle)
        self._districts = districts
        self._session = async_get_clientsession(hass)

    async def _async_update_data(self) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for name, publisher_id in self._districts.items():
            url = feed_url(publisher_id)
            try:
                resp = await self._session.get(url, timeout=30)
                resp.raise_for_status()
                raw = await resp.read()
            except Exception as err:  # noqa: BLE001
                raise UpdateFailed(f"Kunne ikke hente feed for {name}: {err}") from err

            feed = await self.hass.async_add_executor_job(feedparser.parse, raw)
            result[name] = [self._entry_to_dict(e) for e in feed.entries[:MAX_ENTRIES]]
        return result

    @staticmethod
    def _entry_to_dict(entry) -> dict:
        published_iso: str | None = None
        if getattr(entry, "published_parsed", None):
            published_iso = datetime.fromtimestamp(
                mktime(entry.published_parsed)
            ).isoformat()
        title = getattr(entry, "title", "")
        return {
            "title": title,
            "link": getattr(entry, "link", ""),
            "summary": getattr(entry, "summary", ""),
            "published": getattr(entry, "published", ""),
            "published_iso": published_iso,
            "id": getattr(entry, "id", getattr(entry, "link", "")),
            "categories": categorize(title),
        }
