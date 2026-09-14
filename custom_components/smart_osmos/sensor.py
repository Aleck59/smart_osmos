"""Датчики Smart Osmos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import STAGES
from .coordinator import SmartOsmosConfigEntry
from .entity import (
    SmartOsmosDescription,
    SmartOsmosEntity,
    async_add_described_entities,
    stage_label,
)

PARALLEL_UPDATES = 0

PPM = "ppm"
LITERS_PER_MINUTE = "л/мин"


@dataclass(frozen=True, kw_only=True)
class SmartOsmosSensorDescription(SensorEntityDescription, SmartOsmosDescription):
    """Описание датчика Smart Osmos."""


def _as_timestamp(value: Any) -> datetime | None:
    """Превратить unix-время устройства в datetime; 0 означает «неизвестно»."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC)


def _stage_sensors() -> list[SmartOsmosSensorDescription]:
    """Собрать по три датчика на каждую ступень очистки."""
    sensors: list[SmartOsmosSensorDescription] = []
    for stage in STAGES:
        sensors += [
            SmartOsmosSensorDescription(
                key=f"stage_{stage}_remaining",
                name=stage_label(stage, "остаток ресурса"),
                icon="mdi:filter-variant",
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                suggested_display_precision=1,
                field="r",
                stage=stage,
            ),
            SmartOsmosSensorDescription(
                key=f"stage_{stage}_used",
                name=stage_label(stage, "пропущено воды"),
                icon="mdi:water",
                entity_registry_enabled_default=False,
                native_unit_of_measurement=UnitOfVolume.LITERS,
                device_class=SensorDeviceClass.WATER,
                state_class=SensorStateClass.TOTAL_INCREASING,
                suggested_display_precision=1,
                field="u",
                stage=stage,
            ),
            SmartOsmosSensorDescription(
                key=f"stage_{stage}_replaced",
                name=stage_label(stage, "дата замены"),
                icon="mdi:calendar-check",
                device_class=SensorDeviceClass.TIMESTAMP,
                entity_category=EntityCategory.DIAGNOSTIC,
                field="date",
                stage=stage,
            ),
        ]
    return sensors


SENSORS: tuple[SmartOsmosSensorDescription, ...] = (
    SmartOsmosSensorDescription(
        key="tds",
        icon="mdi:water-percent",
        name="TDS",
        native_unit_of_measurement=PPM,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        field="tds",
    ),
    SmartOsmosSensorDescription(
        key="tds_min",
        entity_registry_enabled_default=False,
        icon="mdi:water-percent",
        name="TDS минимум за сутки",
        native_unit_of_measurement=PPM,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        field="tds_min",
    ),
    SmartOsmosSensorDescription(
        key="tds_avg",
        icon="mdi:water-percent",
        name="TDS среднее за сутки",
        native_unit_of_measurement=PPM,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        field="tds_avg",
    ),
    SmartOsmosSensorDescription(
        key="tds_max",
        entity_registry_enabled_default=False,
        icon="mdi:water-percent",
        name="TDS максимум за сутки",
        native_unit_of_measurement=PPM,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        field="tds_max",
    ),
    SmartOsmosSensorDescription(
        key="flow_in",
        icon="mdi:water-pump",
        name="Расход водопровода",
        native_unit_of_measurement=LITERS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        field="f_in",
    ),
    SmartOsmosSensorDescription(
        key="flow_out",
        icon="mdi:water-check",
        name="Расход чистой воды",
        native_unit_of_measurement=LITERS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        field="f_out",
    ),
    SmartOsmosSensorDescription(
        key="minute_in",
        entity_registry_enabled_default=False,
        icon="mdi:water-pump",
        name="Водопровод за минуту",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        field="m_in",
    ),
    SmartOsmosSensorDescription(
        key="minute_out",
        entity_registry_enabled_default=False,
        icon="mdi:cup-water",
        name="Чистая за минуту",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        field="m_out",
    ),
    SmartOsmosSensorDescription(
        key="total_in",
        icon="mdi:counter",
        name="Всего водопроводной воды",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        field="t_in",
    ),
    SmartOsmosSensorDescription(
        key="total_out",
        icon="mdi:counter",
        name="Всего чистой воды",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        field="t_out",
    ),
    SmartOsmosSensorDescription(
        key="purification",
        icon="mdi:chart-donut",
        name="Коэффициент прочистки",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        field="purif",
    ),
    SmartOsmosSensorDescription(
        key="efficiency",
        entity_registry_enabled_default=False,
        icon="mdi:gauge",
        name="Эффективность",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        field="effic",
    ),
    SmartOsmosSensorDescription(
        key="tds_voltage",
        entity_registry_enabled_default=False,
        name="Напряжение TDS-датчика",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=4,
        field="tds_v",
    ),
    SmartOsmosSensorDescription(
        key="calibration_pulses",
        entity_registry_enabled_default=False,
        icon="mdi:pulse",
        name="Импульсов при калибровке",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        field="cal_p",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartOsmosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Создать датчики."""
    async_add_described_entities(
        entry, async_add_entities, SmartOsmosSensor, SENSORS, _stage_sensors()
    )


class SmartOsmosSensor(SmartOsmosEntity, SensorEntity):
    """Датчик, читающий одно поле телеметрии."""

    entity_description: SmartOsmosSensorDescription

    @property
    def native_value(self) -> Any:
        """Текущее значение; для дат — с приведением к datetime."""
        value = self.value
        if self.device_class is SensorDeviceClass.TIMESTAMP:
            return _as_timestamp(value)
        return value
