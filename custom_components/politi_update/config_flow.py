"""Konfigurations-flow: vælg kredse og evt. kategorier."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CATEGORIES,
    CATEGORY_OTHER,
    CONF_CATEGORIES,
    CONF_DISTRICTS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DISTRICTS,
    DOMAIN,
)

DISTRICT_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=list(DISTRICTS.keys()),
        multiple=True,
        mode=SelectSelectorMode.LIST,
    )
)

CATEGORY_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[*CATEGORIES.keys(), CATEGORY_OTHER],
        multiple=True,
        mode=SelectSelectorMode.LIST,
    )
)

INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=1, max=120, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="min"
    )
)


def _schema(districts=None, categories=None, interval=DEFAULT_SCAN_INTERVAL):
    return vol.Schema(
        {
            vol.Required(
                CONF_DISTRICTS, default=districts or []
            ): DISTRICT_SELECTOR,
            vol.Optional(
                CONF_CATEGORIES, default=categories or []
            ): CATEGORY_SELECTOR,
            vol.Optional(
                CONF_SCAN_INTERVAL, default=interval
            ): INTERVAL_SELECTOR,
        }
    )


class PolitiUpdateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Første opsætning."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_DISTRICTS):
                errors["base"] = "no_districts"
            else:
                return self.async_create_entry(
                    title="POLITI UPDATE",
                    data={},
                    options={
                        CONF_DISTRICTS: user_input[CONF_DISTRICTS],
                        CONF_CATEGORIES: user_input.get(CONF_CATEGORIES, []),
                        CONF_SCAN_INTERVAL: int(
                            user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                        ),
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=_schema(), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PolitiUpdateOptionsFlow()


class PolitiUpdateOptionsFlow(OptionsFlow):
    """Ret valg af kredse / kategorier / interval senere."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_DISTRICTS):
                errors["base"] = "no_districts"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_DISTRICTS: user_input[CONF_DISTRICTS],
                        CONF_CATEGORIES: user_input.get(CONF_CATEGORIES, []),
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    },
                )

        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                districts=current.get(CONF_DISTRICTS, []),
                categories=current.get(CONF_CATEGORIES, []),
                interval=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
            errors=errors,
        )
