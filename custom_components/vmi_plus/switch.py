"""Interrupteurs : Boost, vacances, surventilation, débit fixe, préchauffage,
connexion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VmiConfigEntry, protocol
from .const import VACANCES_JOURS_PAR_DEFAUT
from .device import VmiDevice
from .entity import VmiEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class DescriptionInterrupteur(SwitchEntityDescription):
    """Interrupteur porté par un registre et relu dans la trame d'état."""

    registre: int
    valeur_marche: int = 1
    allume: Callable[[protocol.Etat], bool]


# Clés reprises de ha-vmi-plus (identifiants conservés).
INTERRUPTEURS: tuple[DescriptionInterrupteur, ...] = (
    DescriptionInterrupteur(
        key="boost",
        name="Boost",
        icon="mdi:fan-plus",
        registre=protocol.REG_BOOST,
        allume=lambda etat: etat.boost,
    ),
    DescriptionInterrupteur(
        # Le « bypass » de ha-vmi-plus : c'est la marche du préchauffage
        # électrique, jusqu'à 1 800 W. Désactivé d'origine.
        key="bypass",
        name="Préchauffage (marche)",
        icon="mdi:heating-coil",
        entity_registry_enabled_default=False,
        registre=protocol.REG_PRECHAUFFAGE_MARCHE,
        allume=lambda etat: etat.prechauffage_marche,
    ),
    DescriptionInterrupteur(
        # Allumé tant qu'il reste des jours. « Allumer » pose
        # VACANCES_JOURS_PAR_DEFAUT ; le décompte est fait par la VMI.
        key="holiday",
        name="Vacances",
        icon="mdi:palm-tree",
        registre=protocol.REG_VACANCES,
        valeur_marche=VACANCES_JOURS_PAR_DEFAUT,
        allume=lambda etat: etat.vacances_jours > 0,
    ),
    DescriptionInterrupteur(
        # Réglage d'installation (« risque radon avéré » dans VMI+).
        key="fixed_airflow",
        name="Débit fixe",
        icon="mdi:fan-lock",
        entity_category=EntityCategory.CONFIG,
        registre=protocol.REG_DEBIT_FIXE,
        allume=lambda etat: etat.debit_fixe,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VmiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities(
        [
            *(VmiInterrupteur(device, entry, description) for description in INTERRUPTEURS),
            VmiSurventilation(device, entry),
            VmiConnexion(device, entry),
        ]
    )


class VmiInterrupteur(VmiEntity, SwitchEntity):
    entity_description: DescriptionInterrupteur

    def __init__(
        self,
        device: VmiDevice,
        entry: VmiConfigEntry,
        description: DescriptionInterrupteur,
    ) -> None:
        super().__init__(device, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        etat = self._device.etat
        return None if etat is None else self.entity_description.allume(etat)

    async def _regler(self, marche: bool) -> None:
        description = self.entity_description
        await self._device.commander(
            str(description.name),
            description.registre,
            description.valeur_marche if marche else 0,
            lambda etat: description.allume(etat) == marche,
            # « Allumer » ce qui l'est déjà n'envoie rien (des vacances en
            # cours reviendraient à 1 jour) ; « éteindre » part toujours.
            sauf_si_deja=marche,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._regler(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._regler(False)


class VmiSurventilation(VmiEntity, SwitchEntity):
    """Surventilation (le « mode nuit » de ha-vmi-plus).

    Le registre est une bascule : l'état est relu juste avant, et la commande
    n'est envoyée que s'il diffère de l'état voulu.
    """

    _attr_name = "Surventilation"
    _attr_icon = "mdi:weather-night"

    def __init__(self, device: VmiDevice, entry: VmiConfigEntry) -> None:
        super().__init__(device, entry, "night_boost")

    @property
    def is_on(self) -> bool | None:
        etat = self._device.etat
        return None if etat is None else etat.surventilation

    async def _regler(self, voulue: bool) -> None:
        await self._device.commander(
            "Surventilation",
            protocol.REG_SURVENTILATION,
            0,
            lambda etat: etat.surventilation == voulue,
            sauf_si_deja=True,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._regler(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._regler(False)


class VmiConnexion(VmiEntity, SwitchEntity):
    """Connexion Bluetooth de Home Assistant à la VMI.

    La VMI n'accepte qu'une connexion : couper cet interrupteur la libère pour
    l'app VMI+ (maintenance). Toujours disponible, toujours allumé au
    démarrage de Home Assistant.
    """

    _attr_name = "Connexion Bluetooth"
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, device: VmiDevice, entry: VmiConfigEntry) -> None:
        super().__init__(device, entry, "connection_enabled")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._device.active

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._device.regler_active(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._device.regler_active(False)
