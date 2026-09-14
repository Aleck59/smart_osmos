"""Двоичные датчики Smart Osmos."""

from __future__ import annotations

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
from .entity import (
    SmartOsmosDescription,
    SmartOsmosEntity,
    async_add_described_entities,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SmartOsmosBinaryDescription(BinarySensorEntityDescription, SmartOsmosDescription):
    """Описание двоичного датчика Smart Osmos."""


def _any_stage_below(
    coordinator: SmartOsmosCoordinator, threshold: float
) -> bool | None:
    """Есть ли ступень, остаток ресурса которой ниже порога в процентах."""
    remaining = coordinator.value("r")
    if not isinstance(remaining, list) or len(remaining) < STAGE_COUNT:
        return None
    return any(value <= threshold for value in remaining)


BINARY_SENSORS: tuple[SmartOsmosBinaryDescription, ...] = (
    SmartOsmosBinaryDescription(
        key="connected",
        name="Связь",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        available_offline=True,
        value_fn=lambda c: c.available,
    ),
    SmartOsmosBinaryDescription(
        key="replacement_needed",
        icon="mdi:filter-remove",
        name="Требуется замена фильтра",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: _any_stage_below(c, 5),
    ),
    SmartOsmosBinaryDescription(
        key="low_resource",
        icon="mdi:filter-variant-remove",
        name="Ресурс на исходе",
        value_fn=lambda c: _any_stage_below(c, 20),
    ),
    SmartOsmosBinaryDescription(
        key="calibrating",
        icon="mdi:beaker-outline",
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
    async_add_described_entities(
        entry, async_add_entities, SmartOsmosBinarySensor, BINARY_SENSORS
    )


class SmartOsmosBinarySensor(SmartOsmosEntity, BinarySensorEntity):
    """Двоичный датчик Smart Osmos."""

    entity_description: SmartOsmosBinaryDescription

    @property
    def is_on(self) -> bool | None:
        """Текущее состояние."""
        return self.value
