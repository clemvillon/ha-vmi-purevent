"""Vitesse de ventilation.

Un sélecteur et non un ventilateur : la VMI ne s'arrête jamais, alors que le
domaine `fan` impose une position éteinte (choix repris de ha-vmi-plus).
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VmiConfigEntry, protocol
from .const import VITESSES
from .device import VmiDevice
from .entity import VmiEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VmiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([VmiVitesse(entry.runtime_data, entry)])


class VmiVitesse(VmiEntity, SelectEntity):
    _attr_name = "Vitesse"
    _attr_icon = "mdi:fan"
    _attr_options = list(VITESSES)

    def __init__(self, device: VmiDevice, entry: VmiConfigEntry) -> None:
        super().__init__(device, entry, "speed")

    @property
    def current_option(self) -> str | None:
        etat = self._device.etat
        if etat is None or etat.vitesse is None:
            return None
        return VITESSES[etat.vitesse]

    async def async_select_option(self, option: str) -> None:
        vitesse = VITESSES.index(option)
        await self._device.commander(
            "Vitesse",
            protocol.REG_VITESSE,
            vitesse,
            lambda etat: etat.vitesse == vitesse,
        )
