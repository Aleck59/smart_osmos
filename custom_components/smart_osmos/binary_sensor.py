"""Двоичные датчики Smart Osmos."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import STAGE_COUNT
from .coordinator import SmartOsmosConfigEntry, SmartOsmosCoordinator
from .entity import SmartOsmosEntity


@dataclass(frozen=True, kw_only=True)
class SmartOsmosBinaryDescription(BinarySensorEntityDescription):
    """Описание двоичного датчика с функцией вычисления состояния."""

    value_fn: Callable[[SmartOsmosCoordinator], bool | None]
    # Датчик связи должен оставаться доступным, когда связи нет.
    available_offline: bool = False


def _needs_replacement(coordinator: SmartOsmosCoordinator) -> bool | None:
    """Есть ли ступень, ресурс которой практически исчерпан."""
    remaining = coordinator.value("r")
    if not isinstance(remaining, list) or len(remaining) < STAGE_COUNT:
        return None
    return any(value <= 5 for value in remaining)


def _low_resource(coordinator: SmartOsmosCoordinator) -> bool | None:
    """Есть ли ступень с остатком менее 20 %."""
    remaining = coordinator.value("r")
    if not isinstance(remaining, list) or len(remaining) < STAGE_COUNT:
        return None
    return any(value < 20 for value in remaining)


BINARY_SENSORS: tuple[SmartOsmosBinaryDescription, ...] = (
    SmartOsmosBinaryDescription(
        key="connected",
        name="Связь",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        available_offline=True,
        value_fn=lambda c: c.connected,
    ),
    SmartOsmosBinaryDescription(
        key="replacement_needed",
        name="Требуется замена фильтра",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_needs_replacement,
    ),
    SmartOsmosBinaryDescription(
        key="low_resource",
        name="Ресурс на исходе",
        value_fn=_low_resource,
    ),
    SmartOsmosBinaryDescription(
        key="calibrating",
        name="Идёт калибровка",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: bool(c.value("cal")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartOsmosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Создать двоичные датчики."""
    coordinator = entry.runtime_data
    async_add_entities(
        SmartOsmosBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class SmartOsmosBinarySensor(SmartOsmosEntity, BinarySensorEntity):
    """Двоичный датчик Smart Osmos."""

    entity_description: SmartOsmosBinaryDescription

    @property
    def available(self) -> bool:
        """Датчик связи доступен всегда, остальные — только при соединении."""
        if self.entity_description.available_offline:
            return True
        return super().available

    @property
    def is_on(self) -> bool | None:
        """Текущее состояние."""
        return self.entity_description.value_fn(self.coordinator)
