"""VMI Ventilairsec Purevent (VisionAir) par Bluetooth.

Remplace ha-vmi-plus (même domaine, mêmes identifiants d'entités) ; voir
NOTICE pour l'origine du code.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant

from .device import VmiDevice

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type VmiConfigEntry = ConfigEntry[VmiDevice]


async def async_setup_entry(hass: HomeAssistant, entry: VmiConfigEntry) -> bool:
    """Charge l'entrée sans attendre la VMI : la liaison se fait en fond."""
    device = VmiDevice(hass, entry, entry.data[CONF_ADDRESS])
    entry.runtime_data = device
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def a_l_arret_de_ha(_evenement: Event) -> None:
        # Rendre l'unique connexion de la VMI plutôt que la laisser au relais.
        await device.arreter()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, a_l_arret_de_ha)
    )
    device.demarrer()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VmiConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.arreter()
    return unload_ok
