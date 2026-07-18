"""Én event-entitet pr. kreds, der udløses ved nye meldinger.

Gør det nemt at bruge nye POLITI UPDATE-meldinger direkte som trigger i
automatiseringer (trigger på event-entiteten frem for at polle en sensor).
"""
from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CATEGORIES, CONF_DISTRICTS, DISTRICTS, DOMAIN, slug_for
from .coordinator import PolitiUpdateCoordinator
from .helpers import filter_by_categories

EVENT_NEW = "ny_melding"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PolitiUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    names = entry.options.get(CONF_DISTRICTS, [])
    categories = entry.options.get(CONF_CATEGORIES, [])
    async_add_entities(
        PolitiUpdateEvent(coordinator, entry, name, categories) for name in names
    )


class PolitiUpdateEvent(CoordinatorEntity[PolitiUpdateCoordinator], EventEntity):
    """Udløses når der kommer en ny melding i kredsen."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:police-badge"
    _attr_event_types = [EVENT_NEW]
    _attr_translation_key = "politi_update"

    def __init__(
        self,
        coordinator: PolitiUpdateCoordinator,
        entry: ConfigEntry,
        district_name: str,
        categories: list[str],
    ) -> None:
        super().__init__(coordinator)
        self._district_name = district_name
        self._categories = categories
        self._last_id: str | None = None
        publisher_id = DISTRICTS.get(district_name)
        self._attr_name = district_name
        self._attr_unique_id = f"{entry.entry_id}_{slug_for(publisher_id)}_event"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="POLITI UPDATE",
            manufacturer="Rigspolitiet / Ritzau",
            entry_type="service",
        )

    def _current_entries(self) -> list[dict]:
        raw = (self.coordinator.data or {}).get(self._district_name, [])
        return filter_by_categories(raw, self._categories)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Husk nyeste ved opstart, så vi ikke udløser på eksisterende meldinger.
        entries = self._current_entries()
        if entries:
            self._last_id = entries[0].get("id")

    @callback
    def _handle_coordinator_update(self) -> None:
        entries = self._current_entries()
        if entries:
            newest = entries[0]
            if newest.get("id") != self._last_id:
                self._last_id = newest.get("id")
                self._trigger_event(
                    EVENT_NEW,
                    {
                        "district": self._district_name,
                        "title": newest.get("title"),
                        "link": newest.get("link"),
                        "published": newest.get("published"),
                        "categories": newest.get("categories"),
                    },
                )
        super()._handle_coordinator_update()
