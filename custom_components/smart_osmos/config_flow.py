"""Мастер добавления контроллера Smart Osmos."""

from __future__ import annotations

from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
import voluptuous as vol

from .const import DEFAULT_LOCAL_NAME, DOMAIN, SERVICE_UUID
from .settings import SETTINGS


def _is_osmos(info: BluetoothServiceInfoBleak) -> bool:
    """Похоже ли найденное устройство на контроллер Smart Osmos."""
    if SERVICE_UUID.lower() in {uuid.lower() for uuid in info.service_uuids}:
        return True
    return (info.name or "").strip().upper() == DEFAULT_LOCAL_NAME


class SmartOsmosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Добавление устройства: автообнаружение по BLE или выбор из списка."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SmartOsmosOptionsFlow:
        """Вернуть форму настроек устройства."""
        return SmartOsmosOptionsFlow()

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


class SmartOsmosOptionsFlow(OptionsFlow):
    """Все настройки контроллера одной формой.

    Значения не хранятся в Home Assistant: форма читает их прямо из устройства
    и отправляет обратно только то, что изменилось.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Показать настройки и записать изменения в устройство."""
        coordinator = self.config_entry.runtime_data
        if not coordinator.connected:
            return self.async_abort(reason="not_connected")

        current = {
            setting.key: coordinator.read(setting.field, setting.stage)
            for setting in SETTINGS
        }

        if user_input is not None:
            for setting in SETTINGS:
                new = user_input.get(setting.key)
                if new is None:
                    continue
                was = current[setting.key]
                if was is not None and abs(float(was) - float(new)) < 1e-9:
                    continue
                await coordinator.async_send_command(setting.payload_fn(float(new)))
            await coordinator.async_refresh_config()
            return self.async_create_entry(data={})

        schema = vol.Schema(
            {
                vol.Required(setting.key): NumberSelector(
                    NumberSelectorConfig(
                        min=setting.minimum,
                        max=setting.maximum,
                        step=setting.step,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement=setting.unit,
                    )
                )
                for setting in SETTINGS
            }
        )
        known = {key: value for key, value in current.items() if value is not None}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, known),
        )
