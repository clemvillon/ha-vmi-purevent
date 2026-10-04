"""Diagnostic téléchargeable de l'entrée : état de la liaison et dernières
trames reçues, adresse Bluetooth masquée."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from . import VmiConfigEntry

A_MASQUER = {CONF_ADDRESS}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VmiConfigEntry
) -> dict[str, Any]:
    return {
        "entry_data": async_redact_data(dict(entry.data), A_MASQUER),
        **entry.runtime_data.diagnostic(),
    }
