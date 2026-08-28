"""Базовая сущность Smart Osmos."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartOsmosCoordinator


class SmartOsmosEntity(CoordinatorEntity[SmartOsmosCoordinator]):
    """Общий предок всех сущностей интеграции."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SmartOsmosCoordinator, description: EntityDescription
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
        """Сущность доступна, пока держится BLE-соединение."""
        return self.coordinator.connected
