"""Én sensor pr. valgt politikreds."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CATEGORIES, CONF_DISTRICTS, DISTRICTS, DOMAIN, slug_for
from .coordinator import PolitiUpdateCoordinator
from .helpers import filter_by_categories


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PolitiUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    names = entry.options.get(CONF_DISTRICTS, [])
    categories = entry.options.get(CONF_CATEGORIES, [])
    async_add_entities(
        PolitiUpdateSensor(coordinator, entry, name, categories) for name in names
    )


class PolitiUpdateSensor(CoordinatorEntity[PolitiUpdateCoordinator], SensorEntity):
    """Viser antal nyheder + de seneste meldinger for en kreds."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:police-badge"

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
        publisher_id = DISTRICTS.get(district_name)
        self._attr_name = district_name
        self._attr_unique_id = f"{entry.entry_id}_{slug_for(publisher_id)}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="POLITI UPDATE",
            manufacturer="Rigspolitiet / Ritzau",
            entry_type="service",
        )

    @property
    def _entries(self) -> list[dict]:
        raw = (self.coordinator.data or {}).get(self._district_name, [])
        return filter_by_categories(raw, self._categories)

    @property
    def native_value(self) -> int:
        # Tilstand = antal aktuelle (filtrerede) nyheder.
        return len(self._entries)

    @property
    def extra_state_attributes(self) -> dict:
        entries = self._entries
        latest = entries[0] if entries else {}
        return {
            "district": self._district_name,
            "filter_categories": self._categories or "alle",
            "latest_title": latest.get("title"),
            "latest_link": latest.get("link"),
            "latest_published": latest.get("published"),
            "latest_categories": latest.get("categories"),
            "entries": entries,
        }
