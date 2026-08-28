"""Кнопки Smart Osmos: сброс ресурса, счётчиков и калибровка."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import STAGE_COUNT, STAGE_NAMES
from .coordinator import SmartOsmosConfigEntry, SmartOsmosCoordinator
from .entity import SmartOsmosEntity


@dataclass(frozen=True, kw_only=True)
class SmartOsmosButtonDescription(ButtonEntityDescription):
    """Описание кнопки с командой, отправляемой устройству."""

    press_fn: Callable[[SmartOsmosCoordinator], Coroutine[Any, Any, None]]


def _stage_buttons() -> list[SmartOsmosButtonDescription]:
    """Кнопка «заменил фильтр» для каждой ступени."""
    return [
        SmartOsmosButtonDescription(
            key=f"reset_stage_{stage}",
            name=f"{stage}. {STAGE_NAMES[stage]}: отметить замену",
            entity_category=EntityCategory.CONFIG,
            press_fn=lambda c, s=stage: c.async_send_command(
                {"key": "stage", "n": s, "reset": "R"}
            ),
        )
        for stage in range(1, STAGE_COUNT + 1)
    ]


BUTTONS: tuple[SmartOsmosButtonDescription, ...] = (
    SmartOsmosButtonDescription(
        key="reset_totals",
        name="Обнулить суммарные счётчики",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_send_command(
            {"key": "c_reset", "r_totalIN_OUT": "R"}
        ),
    ),
    SmartOsmosButtonDescription(
        key="reset_day_stats",
        name="Сбросить суточную статистику TDS",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_send_command({"key": "tds_cal", "act": "day_reset"}),
    ),
    SmartOsmosButtonDescription(
        key="calibration_start",
        name="Калибровка: старт",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_send_command({"key": "cal", "act": "start"}),
    ),
    SmartOsmosButtonDescription(
        key="calibration_finish",
        name="Калибровка: налит 1 литр",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_send_command(
            {"key": "cal", "act": "finish", "l": 1}
        ),
    ),
    SmartOsmosButtonDescription(
        key="calibration_cancel",
        name="Калибровка: отмена",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.async_send_command({"key": "cal", "act": "cancel"}),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartOsmosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Создать кнопки."""
    coordinator = entry.runtime_data
    async_add_entities(
        SmartOsmosButton(coordinator, description)
        for description in (*BUTTONS, *_stage_buttons())
    )


class SmartOsmosButton(SmartOsmosEntity, ButtonEntity):
    """Кнопка, отправляющая одну команду контроллеру."""

    entity_description: SmartOsmosButtonDescription

    async def async_press(self) -> None:
        """Отправить команду устройству."""
        await self.entity_description.press_fn(self.coordinator)
