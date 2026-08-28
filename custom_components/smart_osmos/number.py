"""Настройки Smart Osmos, доступные из Home Assistant."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import STAGE_COUNT, STAGE_NAMES
from .coordinator import SmartOsmosConfigEntry, SmartOsmosCoordinator
from .entity import SmartOsmosEntity


@dataclass(frozen=True, kw_only=True)
class SmartOsmosNumberDescription(NumberEntityDescription):
    """Описание настройки: как её прочитать и как записать."""

    value_fn: Callable[[SmartOsmosCoordinator], Any]
    set_fn: Callable[[SmartOsmosCoordinator, float], Coroutine[Any, Any, None]]


def _stage_limits() -> list[SmartOsmosNumberDescription]:
    """Ресурс каждой ступени в литрах."""
    return [
        SmartOsmosNumberDescription(
            key=f"stage_{stage}_limit",
            name=f"{stage}. {STAGE_NAMES[stage]}: ресурс",
            native_unit_of_measurement=UnitOfVolume.LITERS,
            native_min_value=0,
            native_max_value=30000,
            native_step=100,
            mode=NumberMode.BOX,
            entity_category=EntityCategory.CONFIG,
            value_fn=lambda c, s=stage: c.stage_value("limit", s),
            set_fn=lambda c, v, s=stage: c.async_send_command(
                {"key": "stage", "n": s, "limit": int(v)}
            ),
        )
        for stage in range(1, STAGE_COUNT + 1)
    ]


NUMBERS: tuple[SmartOsmosNumberDescription, ...] = (
    SmartOsmosNumberDescription(
        key="pulses_per_liter_in",
        name="Импульсов на литр (водопровод)",
        native_min_value=100,
        native_max_value=20000,
        native_step=10,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.value("c_in"),
        set_fn=lambda c, v: c.async_send_command({"key": "c_config", "c_in": int(v)}),
    ),
    SmartOsmosNumberDescription(
        key="pulses_per_liter_out",
        name="Импульсов на литр (чистая)",
        native_min_value=100,
        native_max_value=20000,
        native_step=10,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.value("c_out"),
        set_fn=lambda c, v: c.async_send_command({"key": "c_config", "c_off": int(v)}),
    ),
    SmartOsmosNumberDescription(
        key="tds_factor",
        name="Множитель калибровки TDS",
        native_min_value=0.2,
        native_max_value=3.0,
        native_step=0.01,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.value("tds_factor"),
        set_fn=lambda c, v: c.async_send_command(
            {"key": "tds_cal", "factor": round(v, 4)}
        ),
    ),
    SmartOsmosNumberDescription(
        key="tds_offset",
        name="Смещение калибровки TDS",
        native_unit_of_measurement="ppm",
        native_min_value=-200,
        native_max_value=200,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.value("tds_offset"),
        set_fn=lambda c, v: c.async_send_command(
            {"key": "tds_cal", "offset": round(v, 2)}
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartOsmosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Создать настройки."""
    coordinator = entry.runtime_data
    async_add_entities(
        SmartOsmosNumber(coordinator, description)
        for description in (*NUMBERS, *_stage_limits())
    )


class SmartOsmosNumber(SmartOsmosEntity, NumberEntity):
    """Настройка, которая читается из устройства и записывается в него."""

    entity_description: SmartOsmosNumberDescription

    @property
    def native_value(self) -> float | None:
        """Текущее значение настройки."""
        value = self.entity_description.value_fn(self.coordinator)
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        """Записать новое значение в устройство."""
        await self.entity_description.set_fn(self.coordinator, value)
        # Сразу перечитываем конфигурацию, чтобы интерфейс показал новое значение.
        await self.coordinator.async_refresh_config()
