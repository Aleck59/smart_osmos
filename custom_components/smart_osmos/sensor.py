"""Датчики Smart Osmos."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import STAGE_COUNT, STAGE_NAMES
from .coordinator import SmartOsmosConfigEntry, SmartOsmosCoordinator
from .entity import SmartOsmosEntity

PPM = "ppm"
LITERS_PER_MINUTE = "л/мин"


@dataclass(frozen=True, kw_only=True)
class SmartOsmosSensorDescription(SensorEntityDescription):
    """Описание датчика с функцией извлечения значения."""

    value_fn: Callable[[SmartOsmosCoordinator], Any]


def _stage_descriptions() -> list[SmartOsmosSensorDescription]:
    """Собрать по три датчика на каждую ступень очистки."""
    result: list[SmartOsmosSensorDescription] = []
    for stage in range(1, STAGE_COUNT + 1):
        label = STAGE_NAMES[stage]
        result.extend(
            [
                SmartOsmosSensorDescription(
                    key=f"stage_{stage}_remaining",
                    name=f"{stage}. {label}: остаток ресурса",
                    native_unit_of_measurement="%",
                    state_class=SensorStateClass.MEASUREMENT,
                    suggested_display_precision=1,
                    value_fn=lambda c, s=stage: c.stage_value("r", s),
                ),
                SmartOsmosSensorDescription(
                    key=f"stage_{stage}_used",
                    name=f"{stage}. {label}: пропущено воды",
                    native_unit_of_measurement=UnitOfVolume.LITERS,
                    device_class=SensorDeviceClass.WATER,
                    state_class=SensorStateClass.TOTAL_INCREASING,
                    suggested_display_precision=1,
                    value_fn=lambda c, s=stage: c.stage_value("u", s),
                ),
                SmartOsmosSensorDescription(
                    key=f"stage_{stage}_replaced",
                    name=f"{stage}. {label}: дата замены",
                    device_class=SensorDeviceClass.TIMESTAMP,
                    entity_category=EntityCategory.DIAGNOSTIC,
                    value_fn=lambda c, s=stage: _as_timestamp(c.stage_value("date", s)),
                ),
            ]
        )
    return result


def _as_timestamp(value: Any) -> datetime | None:
    """Превратить unix-время устройства в datetime; 0 означает «неизвестно»."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC)


SENSORS: tuple[SmartOsmosSensorDescription, ...] = (
    SmartOsmosSensorDescription(
        key="tds",
        name="TDS",
        native_unit_of_measurement=PPM,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda c: c.value("tds"),
    ),
    SmartOsmosSensorDescription(
        key="tds_min",
        name="TDS минимум за сутки",
        native_unit_of_measurement=PPM,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda c: c.value("tds_min"),
    ),
    SmartOsmosSensorDescription(
        key="tds_avg",
        name="TDS среднее за сутки",
        native_unit_of_measurement=PPM,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda c: c.value("tds_avg"),
    ),
    SmartOsmosSensorDescription(
        key="tds_max",
        name="TDS максимум за сутки",
        native_unit_of_measurement=PPM,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda c: c.value("tds_max"),
    ),
    SmartOsmosSensorDescription(
        key="flow_in",
        name="Расход водопровода",
        native_unit_of_measurement=LITERS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda c: c.value("f_in"),
    ),
    SmartOsmosSensorDescription(
        key="flow_out",
        name="Расход чистой воды",
        native_unit_of_measurement=LITERS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda c: c.value("f_out"),
    ),
    SmartOsmosSensorDescription(
        key="minute_in",
        name="Водопровод за минуту",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda c: c.value("m_in"),
    ),
    SmartOsmosSensorDescription(
        key="minute_out",
        name="Чистая за минуту",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda c: c.value("m_out"),
    ),
    SmartOsmosSensorDescription(
        key="total_in",
        name="Всего водопроводной воды",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda c: c.value("t_in"),
    ),
    SmartOsmosSensorDescription(
        key="total_out",
        name="Всего чистой воды",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda c: c.value("t_out"),
    ),
    SmartOsmosSensorDescription(
        key="purification",
        name="Коэффициент прочистки",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda c: c.value("purif"),
    ),
    SmartOsmosSensorDescription(
        key="efficiency",
        name="Эффективность",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda c: c.value("effic"),
    ),
    SmartOsmosSensorDescription(
        key="tds_voltage",
        name="Напряжение TDS-датчика",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=4,
        value_fn=lambda c: c.value("tds_v"),
    ),
    SmartOsmosSensorDescription(
        key="calibration_pulses",
        name="Импульсов при калибровке",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.value("cal_p"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartOsmosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Создать датчики."""
    coordinator = entry.runtime_data
    async_add_entities(
        SmartOsmosSensor(coordinator, description)
        for description in (*SENSORS, *_stage_descriptions())
    )


class SmartOsmosSensor(SmartOsmosEntity, SensorEntity):
    """Датчик, читающий одно поле телеметрии."""

    entity_description: SmartOsmosSensorDescription

    @property
    def native_value(self) -> Any:
        """Текущее значение."""
        return self.entity_description.value_fn(self.coordinator)
