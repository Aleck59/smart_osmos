"""Кнопки Smart Osmos: отметка замены, сброс счётчиков и калибровка."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
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

# Запись в BLE-характеристику — операция последовательная.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class SmartOsmosButtonDescription(ButtonEntityDescription, SmartOsmosDescription):
    """Описание кнопки: какую команду отправить устройству."""

    command: dict[str, Any]


def _stage_buttons() -> list[SmartOsmosButtonDescription]:
    """Кнопка «отметить замену» для каждой ступени."""
    return [
        SmartOsmosButtonDescription(
            key=f"reset_stage_{stage}",
            name=stage_label(stage, "отметить замену"),
            icon="mdi:filter-check",
            entity_category=EntityCategory.CONFIG,
            command={"key": "stage", "n": stage, "reset": "R"},
        )
        for stage in STAGES
    ]


BUTTONS: tuple[SmartOsmosButtonDescription, ...] = (
    SmartOsmosButtonDescription(
        key="reset_totals",
        icon="mdi:restart",
        name="Обнулить суммарные счётчики",
        entity_category=EntityCategory.CONFIG,
        command={"key": "c_reset", "r_totalIN_OUT": "R"},
    ),
    SmartOsmosButtonDescription(
        key="reset_day_stats",
        icon="mdi:chart-timeline-variant",
        name="Сбросить суточную статистику TDS",
        entity_category=EntityCategory.CONFIG,
        command={"key": "tds_cal", "act": "day_reset"},
    ),
    SmartOsmosButtonDescription(
        key="calibration_start",
        icon="mdi:play-circle-outline",
        name="Калибровка: старт",
        entity_category=EntityCategory.CONFIG,
        command={"key": "cal", "act": "start"},
    ),
    SmartOsmosButtonDescription(
        key="calibration_finish",
        icon="mdi:check-circle-outline",
        name="Калибровка: налит 1 литр",
        entity_category=EntityCategory.CONFIG,
        command={"key": "cal", "act": "finish", "l": 1},
    ),
    SmartOsmosButtonDescription(
        key="calibration_cancel",
        icon="mdi:close-circle-outline",
        name="Калибровка: отмена",
        entity_category=EntityCategory.CONFIG,
        command={"key": "cal", "act": "cancel"},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartOsmosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Создать кнопки."""
    async_add_described_entities(
        entry, async_add_entities, SmartOsmosButton, BUTTONS, _stage_buttons()
    )


class SmartOsmosButton(SmartOsmosEntity, ButtonEntity):
    """Кнопка, отправляющая одну команду контроллеру."""

    entity_description: SmartOsmosButtonDescription

    async def async_press(self) -> None:
        """Отправить команду устройству."""
        await self.coordinator.async_send_command(self.entity_description.command)
