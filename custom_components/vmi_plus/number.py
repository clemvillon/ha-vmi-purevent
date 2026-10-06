"""Réglages numériques : vacances, limite d'été, consigne de préchauffage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VmiConfigEntry, protocol
from .device import VmiDevice
from .entity import VmiEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class DescriptionReglage(NumberEntityDescription):
    """Réglage porté par un registre et relu dans la trame d'état."""

    registre: int
    valeur: Callable[[protocol.Etat], int]
    # Valeur de la trame qui veut dire « aucun réglage » et sort de la plage
    # du curseur : l'entité vaut alors « inconnu ».
    valeur_sans_reglage: int | None = None


REGLAGES: tuple[DescriptionReglage, ...] = (
    DescriptionReglage(
        # 0 = pas de vacances. Le décompte des jours est fait par la VMI.
        key="holiday_days",
        name="Vacances (jours)",
        icon="mdi:palm-tree",
        native_min_value=0,
        native_max_value=protocol.VACANCES_MAX_JOURS,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.DAYS,
        mode=NumberMode.BOX,
        registre=protocol.REG_VACANCES,
        valeur=lambda etat: etat.vacances_jours,
    ),
    DescriptionReglage(
        key="summer_limit",
        name="Limite d'été",
        icon="mdi:sun-thermometer-outline",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=protocol.LIMITE_ETE_MIN_C,
        native_max_value=protocol.LIMITE_ETE_MAX_C,
        native_step=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        registre=protocol.REG_LIMITE_ETE,
        valeur=lambda etat: etat.limite_ete_c,
    ),
    DescriptionReglage(
        # Désactivé d'origine : régler une consigne MET LE PRÉCHAUFFAGE EN
        # MARCHE (jusqu'à 1 800 W). Sans consigne (0), l'entité vaut
        # « inconnu » ; pour revenir à 0 : le bouton « Arrêter le préchauffage ».
        key="preheat_temperature",
        name="Préchauffage (consigne)",
        icon="mdi:heating-coil",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=protocol.PRECHAUFFAGE_CONSIGNE_MIN_C,
        native_max_value=protocol.PRECHAUFFAGE_CONSIGNE_MAX_C,
        native_step=1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        entity_registry_enabled_default=False,
        registre=protocol.REG_PRECHAUFFAGE_CONSIGNE,
        valeur=lambda etat: etat.prechauffage_consigne_c,
        valeur_sans_reglage=0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VmiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    device = entry.runtime_data
    async_add_entities(VmiReglage(device, entry, description) for description in REGLAGES)


class VmiReglage(VmiEntity, NumberEntity):
    entity_description: DescriptionReglage

    def __init__(
        self, device: VmiDevice, entry: VmiConfigEntry, description: DescriptionReglage
    ) -> None:
        super().__init__(device, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | None:
        etat = self._device.etat
        if etat is None:
            return None
        valeur = self.entity_description.valeur(etat)
        if valeur == self.entity_description.valeur_sans_reglage:
            return None
        return valeur

    async def async_set_native_value(self, value: float) -> None:
        description = self.entity_description
        voulue = int(value)
        await self._device.commander(
            str(description.name),
            description.registre,
            voulue,
            lambda etat: description.valeur(etat) == voulue,
        )
