"""Общая машинерия сущностей Smart Osmos.

Все четыре платформы устроены одинаково: описание говорит, какое поле
телеметрии показывать (или как его вычислить), сущность это поле достаёт,
а точка входа платформы просто раздаёт описания. Здесь собрано всё, что иначе
повторялось бы в каждом модуле, — в самих платформах остаются только описания.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STAGE_NAMES
from .coordinator import SmartOsmosConfigEntry, SmartOsmosCoordinator

#: Вычисляет значение сущности, если его нельзя просто прочитать из телеметрии.
ValueFn = Callable[[SmartOsmosCoordinator], Any]


@dataclass(frozen=True, kw_only=True)
class SmartOsmosDescription(EntityDescription):
    """Общая часть описания любой сущности Smart Osmos."""

    #: Имя поля в телеметрии устройства.
    field: str | None = None
    #: Номер ступени (1..5), если поле — массив по ступеням.
    stage: int | None = None
    #: Задаётся вместо field, когда значение нужно вычислить.
    value_fn: ValueFn | None = None
    #: Датчик связи обязан оставаться доступным как раз тогда, когда связи нет.
    available_offline: bool = False


def stage_label(stage: int, suffix: str) -> str:
    """Собрать имя сущности, привязанной к ступени очистки."""
    return f"{stage}. {STAGE_NAMES[stage]}: {suffix}"


class SmartOsmosEntity(CoordinatorEntity[SmartOsmosCoordinator]):
    """Общий предок всех сущностей интеграции."""

    _attr_has_entity_name = True
    entity_description: SmartOsmosDescription

    def __init__(
        self, coordinator: SmartOsmosCoordinator, description: SmartOsmosDescription
    ) -> None:
        """Привязать сущность к устройству."""
        super().__init__(coordinator)
        self.entity_description = description
        address = coordinator.address
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            connections={(dr.CONNECTION_BLUETOOTH, address)},
            identifiers={(DOMAIN, address)},
            manufacturer="Smart Osmos",
            model="OSMOS-H2",
            name="Smart Osmos",
        )

    @property
    def available(self) -> bool:
        """Доступна, пока есть связь и данные не устарели."""
        if self.entity_description.available_offline:
            return True
        return self.coordinator.available

    @property
    def value(self) -> Any:
        """Значение сущности: вычисленное или прочитанное из телеметрии."""
        description = self.entity_description
        if description.value_fn is not None:
            return description.value_fn(self.coordinator)
        if description.field is None:
            return None
        return self.coordinator.read(description.field, description.stage)


def async_add_described_entities(
    entry: SmartOsmosConfigEntry,
    async_add_entities: AddEntitiesCallback,
    entity_cls: type[SmartOsmosEntity],
    *groups: Iterable[SmartOsmosDescription],
) -> None:
    """Создать по одной сущности на каждое описание из перечисленных групп."""
    coordinator = entry.runtime_data
    async_add_entities(
        entity_cls(coordinator, description)
        for group in groups
        for description in group
    )
