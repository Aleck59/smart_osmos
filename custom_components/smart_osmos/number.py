"""Настройки Smart Osmos как отдельные сущности.

Те же настройки собраны в одну форму «Настроить» у интеграции, поэтому по
умолчанию эти сущности выключены — включайте те, что нужны в автоматизациях.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SmartOsmosConfigEntry
from .entity import (
    SmartOsmosDescription,
    SmartOsmosEntity,
    async_add_described_entities,
)
from .settings import SETTINGS, PayloadFn

# Запись в BLE-характеристику — операция последовательная.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SmartOsmosNumberDescription(NumberEntityDescription, SmartOsmosDescription):
    """Описание настройки: какое поле читать и какую команду записывать."""

    payload_fn: PayloadFn


NUMBERS: tuple[SmartOsmosNumberDescription, ...] = tuple(
    SmartOsmosNumberDescription(
        key=setting.key,
        name=setting.name,
        icon=setting.icon,
        field=setting.field,
        stage=setting.stage,
        native_min_value=setting.minimum,
        native_max_value=setting.maximum,
        native_step=setting.step,
        native_unit_of_measurement=setting.unit,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        payload_fn=setting.payload_fn,
    )
    for setting in SETTINGS
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartOsmosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Создать настройки."""
    async_add_described_entities(entry, async_add_entities, SmartOsmosNumber, NUMBERS)


class SmartOsmosNumber(SmartOsmosEntity, NumberEntity):
    """Настройка, которая читается из устройства и записывается в него."""

    entity_description: SmartOsmosNumberDescription

    @property
    def native_value(self) -> float | None:
        """Текущее значение настройки."""
        value = self.value
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        """Записать новое значение в устройство."""
        await self.coordinator.async_send_command(
            self.entity_description.payload_fn(value)
        )
        # Сразу перечитываем конфигурацию, чтобы интерфейс показал новое значение.
        await self.coordinator.async_refresh_config()
