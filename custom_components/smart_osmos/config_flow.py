"""Мастер добавления контроллера Smart Osmos."""

from __future__ import annotations

from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
import voluptuous as vol

from .const import DEFAULT_LOCAL_NAME, DOMAIN, SERVICE_UUID


def _is_osmos(info: BluetoothServiceInfoBleak) -> bool:
    """Похоже ли найденное устройство на контроллер Smart Osmos."""
    if SERVICE_UUID.lower() in {uuid.lower() for uuid in info.service_uuids}:
        return True
    return (info.name or "").strip().upper() == DEFAULT_LOCAL_NAME


class SmartOsmosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Добавление устройства: автообнаружение по BLE или выбор из списка."""

    VERSION = 1

    def __init__(self) -> None:
        """Подготовить состояние мастера."""
        self._discovered: dict[str, str] = {}
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Устройство найдено подсистемой Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not _is_osmos(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or "Smart Osmos"
        }
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Подтверждение добавления найденного устройства."""
        assert self._discovery_info is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name or "Smart Osmos",
                data={CONF_ADDRESS: self._discovery_info.address},
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._discovery_info.name or "Smart Osmos",
                "address": self._discovery_info.address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ручное добавление: выбор из устройств, видимых адаптеру."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=self._discovered.get(address, "Smart Osmos"),
                data={CONF_ADDRESS: address},
            )

        current = self._async_current_ids()
        self._discovered = {
            info.address: f"{info.name or 'Smart Osmos'} ({info.address})"
            for info in async_discovered_service_info(self.hass, connectable=True)
            if _is_osmos(info) and info.address not in current
        }
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered)}
            ),
        )
