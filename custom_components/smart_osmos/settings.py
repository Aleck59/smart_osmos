"""Единый список настроек устройства.

Из него строятся и сущности `number`, и форма «Настроить» у интеграции, поэтому
пределы, единицы и команды описаны ровно один раз и не могут разъехаться.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.const import UnitOfVolume

from .const import STAGE_NAMES, STAGES

PPM = "ppm"

#: Собирает команду для устройства из нового значения настройки.
PayloadFn = Callable[[float], dict[str, Any]]


@dataclass(frozen=True, kw_only=True)
class DeviceSetting:
    """Одна настройка контроллера."""

    key: str
    name: str
    #: Поле, в котором устройство отдаёт текущее значение.
    field: str
    #: Номер ступени (1..5), если поле — массив по ступеням.
    stage: int | None = None
    minimum: float
    maximum: float
    step: float
    unit: str | None = None
    icon: str | None = None
    #: Собирает команду для устройства из нового значения.
    payload_fn: PayloadFn


def _stage_settings() -> tuple[DeviceSetting, ...]:
    """Ресурс каждой ступени в литрах."""
    return tuple(
        DeviceSetting(
            key=f"stage_{stage}_limit",
            name=f"{stage}. {STAGE_NAMES[stage]}: ресурс",
            field="limit",
            stage=stage,
            minimum=0,
            maximum=30000,
            step=100,
            unit=UnitOfVolume.LITERS,
            icon="mdi:filter-variant",
            payload_fn=lambda v, s=stage: {"key": "stage", "n": s, "limit": int(v)},
        )
        for stage in STAGES
    )


SETTINGS: tuple[DeviceSetting, ...] = (
    DeviceSetting(
        key="pulses_per_liter_in",
        name="Импульсов на литр (водопровод)",
        field="c_in",
        minimum=100,
        maximum=20000,
        step=10,
        icon="mdi:water-pump",
        payload_fn=lambda v: {"key": "c_config", "c_in": int(v)},
    ),
    DeviceSetting(
        key="pulses_per_liter_out",
        name="Импульсов на литр (чистая)",
        field="c_out",
        minimum=100,
        maximum=20000,
        step=10,
        icon="mdi:water-check",
        payload_fn=lambda v: {"key": "c_config", "c_off": int(v)},
    ),
    DeviceSetting(
        key="tds_factor",
        name="Множитель калибровки TDS",
        field="tds_factor",
        minimum=0.2,
        maximum=3.0,
        step=0.01,
        icon="mdi:tune-variant",
        payload_fn=lambda v: {"key": "tds_cal", "factor": round(v, 4)},
    ),
    DeviceSetting(
        key="tds_offset",
        name="Смещение калибровки TDS",
        field="tds_offset",
        minimum=-200,
        maximum=200,
        step=1,
        unit=PPM,
        icon="mdi:tune-variant",
        payload_fn=lambda v: {"key": "tds_cal", "offset": round(v, 2)},
    ),
    *_stage_settings(),
)
