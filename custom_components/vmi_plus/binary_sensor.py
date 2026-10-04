"""Capteurs binaires : liaison et préchauffage."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VmiConfigEntry
from .device import VmiDevice
from .entity import VmiEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VmiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities(
        [VmiConnectee(device, entry), VmiPrechauffageEnMarche(device, entry)]
    )


class VmiConnectee(VmiEntity, BinarySensorEntity):
    """Liaison avec la VMI : ouverte, et trame d'état valide reçue récemment.

    Toujours disponible : c'est elle qui dit la perte de liaison.
    """

    _attr_name = "Connectée"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: VmiDevice, entry: VmiConfigEntry) -> None:
        super().__init__(device, entry, "connected")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._device.connectee


class VmiPrechauffageEnMarche(VmiEntity, BinarySensorEntity):
    """Préchauffage électrique en marche (jusqu'à 1 800 W). Lecture seule."""

    _attr_name = "Préchauffage en marche"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, device: VmiDevice, entry: VmiConfigEntry) -> None:
        super().__init__(device, entry, "preheat_active")

    @property
    def is_on(self) -> bool | None:
        etat = self._device.etat
        return None if etat is None else etat.prechauffage_marche
