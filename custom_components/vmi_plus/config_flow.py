"""Ajout d'une VMI : par découverte Bluetooth seulement."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN, SERVICE_COMMANDE_UUID


class VmiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Une VMI est proposée quand son annonce Bluetooth est vue."""

    VERSION = 1

    def __init__(self) -> None:
        self._decouvertes: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        nom = discovery_info.name or discovery_info.address
        self._decouvertes = {discovery_info.address: nom}
        self.context["title_placeholders"] = {"name": nom}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            adresse, nom = next(iter(self._decouvertes.items()))
            return self.async_create_entry(title=nom, data={CONF_ADDRESS: adresse})
        self._set_confirm_only()
        return self.async_show_form(step_id="confirm")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            adresse = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(adresse, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._decouvertes[adresse], data={CONF_ADDRESS: adresse}
            )

        deja = self._async_current_ids()
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in deja:
                continue
            if SERVICE_COMMANDE_UUID in (info.service_uuids or []):
                self._decouvertes[info.address] = info.name or info.address

        if not self._decouvertes:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._decouvertes)}
            ),
        )
