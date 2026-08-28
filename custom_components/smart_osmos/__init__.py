"""Интеграция Smart Osmos — контроллер обратного осмоса по Bluetooth LE."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import SmartOsmosConfigEntry, SmartOsmosCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: SmartOsmosConfigEntry) -> bool:
    """Поднять запись конфигурации."""
    address = entry.unique_id
    if address is None:
        raise ConfigEntryNotReady("У записи нет BLE-адреса устройства")

    coordinator = SmartOsmosCoordinator(hass, entry, address)
    try:
        await coordinator.async_start()
    except Exception as err:
        await coordinator.async_stop()
        raise ConfigEntryNotReady(
            f"Не удалось подключиться к Smart Osmos {address}: {err}"
        ) from err

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SmartOsmosConfigEntry) -> bool:
    """Выгрузить запись конфигурации."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok
