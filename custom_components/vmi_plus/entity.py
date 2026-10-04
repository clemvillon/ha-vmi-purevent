"""Base commune des entités de la VMI."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, MANUFACTURER, MODEL
from .device import VmiDevice


class VmiEntity(Entity):
    """Entité rattachée à la VMI.

    Indisponible dès que la VMI n'est plus connectée : une perte de liaison
    se voit (`unavailable`), elle ne se cache pas derrière la dernière valeur.
    L'état vient toujours d'une trame reçue, jamais d'une commande envoyée.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: VmiDevice, entry: ConfigEntry, cle: str) -> None:
        self._device = device
        adresse = entry.data[CONF_ADDRESS]
        # Mêmes identifiants que ha-vmi-plus : les entités et l'appareil
        # existants sont repris tels quels.
        self._attr_unique_id = f"{adresse}_{cle}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, adresse)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def available(self) -> bool:
        return self._device.connectee and self._device.etat is not None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._device.ajouter_ecouteur(self.async_write_ha_state))
