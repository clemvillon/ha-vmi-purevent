"""Capteurs : sondes, filtre, débit, préchauffage, diagnostic."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VmiConfigEntry, protocol
from .device import (
    HUMIDITE_1,
    TELECOMMANDE_HUMIDITE,
    TELECOMMANDE_TEMPERATURE,
    TEMPERATURE_1,
    TEMPERATURE_2,
    VmiDevice,
)
from .entity import VmiEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class DescriptionMesure(SensorEntityDescription):
    """Capteur alimenté par une mesure filtrée (sondes, télécommande)."""

    mesure: str


@dataclass(frozen=True, kw_only=True)
class DescriptionEtat(SensorEntityDescription):
    """Capteur alimenté par la trame d'état."""

    valeur: Callable[[protocol.Etat], int | str]


# Les quatre premières clés et leurs noms sont ceux de ha-vmi-plus.
MESURES: tuple[DescriptionMesure, ...] = (
    DescriptionMesure(
        key="probe_temperature",
        name="Température sonde interne",
        mesure=TEMPERATURE_1,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DescriptionMesure(
        key="probe_humidity",
        name="Humidité sonde interne",
        mesure=HUMIDITE_1,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DescriptionMesure(
        key="remote_temperature",
        name="Température pièce",
        mesure=TELECOMMANDE_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DescriptionMesure(
        key="remote_humidity",
        name="Humidité pièce",
        mesure=TELECOMMANDE_HUMIDITE,
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DescriptionMesure(
        key="probe2_temperature",
        name="Température entrée d'air",
        mesure=TEMPERATURE_2,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

ETATS: tuple[DescriptionEtat, ...] = (
    DescriptionEtat(
        key="filter_days",
        name="Filtre, jours restants",
        icon="mdi:air-filter",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        valeur=lambda etat: etat.jours_filtre,
    ),
    DescriptionEtat(
        key="airflow",
        name="Débit théorique",
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        valeur=lambda etat: etat.debit_m3h,
    ),
    DescriptionEtat(
        # 0 = pas de préchauffage. Lecture seule : sert à voir une consigne
        # posée ailleurs (VMI+, plages horaires).
        key="preheat_setpoint",
        name="Consigne de préchauffage",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        valeur=lambda etat: etat.prechauffage_consigne_c,
    ),
    DescriptionEtat(
        key="operating_days",
        name="Jours de fonctionnement",
        icon="mdi:counter",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        valeur=lambda etat: etat.jours_fonctionnement,
    ),
    DescriptionEtat(
        key="volume",
        name="Volume à ventiler",
        icon="mdi:cube-outline",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        valeur=lambda etat: etat.volume_m3,
    ),
    DescriptionEtat(
        # La trame d'état telle que reçue, en hexadécimal (61 octets) : pour
        # surveiller ce qui n'est pas décodé, dont l'octet 36.
        key="raw_state",
        name="Trame d'état",
        icon="mdi:code-brackets",
        entity_category=EntityCategory.DIAGNOSTIC,
        valeur=lambda etat: etat.brute,
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
            *(VmiMesure(device, entry, description) for description in MESURES),
            *(VmiCapteurEtat(device, entry, description) for description in ETATS),
        ]
    )


class VmiMesure(VmiEntity, SensorEntity):
    entity_description: DescriptionMesure

    def __init__(
        self, device: VmiDevice, entry: VmiConfigEntry, description: DescriptionMesure
    ) -> None:
        super().__init__(device, entry, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return self._device.mesure_disponible(self.entity_description.mesure)

    @property
    def native_value(self) -> int | None:
        return self._device.mesures[self.entity_description.mesure]


class VmiCapteurEtat(VmiEntity, SensorEntity):
    entity_description: DescriptionEtat

    def __init__(
        self, device: VmiDevice, entry: VmiConfigEntry, description: DescriptionEtat
    ) -> None:
        super().__init__(device, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | str | None:
        etat = self._device.etat
        return None if etat is None else self.entity_description.valeur(etat)
