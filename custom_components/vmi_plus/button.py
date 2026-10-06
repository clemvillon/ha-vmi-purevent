"""Bouton d'arrêt du préchauffage."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VmiConfigEntry
from .device import VmiDevice
from .entity import VmiEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VmiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([VmiArretPrechauffage(entry.runtime_data, entry)])


class VmiArretPrechauffage(VmiEntity, ButtonEntity):
    """Arrête le préchauffage électrique et retire sa consigne.

    Seule commande du préchauffage activée d'origine : elle ne peut que
    baisser la puissance. C'est aussi l'action d'un futur délestage.
    """

    _attr_name = "Arrêter le préchauffage"
    _attr_icon = "mdi:heating-coil"

    def __init__(self, device: VmiDevice, entry: VmiConfigEntry) -> None:
        super().__init__(device, entry, "preheat_stop")

    async def async_press(self) -> None:
        await self._device.arreter_prechauffage()
