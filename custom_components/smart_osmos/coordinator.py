"""Поддержание BLE-соединения с контроллером Smart Osmos."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CHAR_APP_UUID,
    CHAR_EXT_CONFIG_UUID,
    CHAR_EXT_UUID,
    DOMAIN,
    RECONNECT_DELAY,
    STALE_AFTER,
    TIME_SYNC_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

SmartOsmosConfigEntry = ConfigEntry["SmartOsmosCoordinator"]


class SmartOsmosCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Держит соединение с устройством и раздаёт его телеметрию сущностям.

    Прошивка сама шлёт уведомления (телеметрию — раз в 2 с, конфигурацию — раз
    в 30 с), поэтому опроса нет: координатор работает только на push.
    """

    def __init__(
        self, hass: HomeAssistant, entry: SmartOsmosConfigEntry, address: str
    ) -> None:
        """Инициализировать координатор для устройства по адресу address."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {address}",
            update_interval=None,
        )
        self.address = address
        self.data = {}
        self._client: BleakClient | None = None
        self._connect_lock = asyncio.Lock()
        # BLE не терпит параллельных записей в одну характеристику.
        self._write_lock = asyncio.Lock()
        self._closing = False
        self._reconnect_task: asyncio.Task | None = None
        self._time_sync_task: asyncio.Task | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Опроса нет — устройство само шлёт уведомления."""
        return self.data

    # ------------------------------------------------------------------ доступ
    @property
    def connected(self) -> bool:
        """Установлено ли соединение с устройством."""
        return self._client is not None and self._client.is_connected

    @property
    def available(self) -> bool:
        """Есть связь и данные не устарели."""
        if not self.connected:
            return False
        last_seen = self.data.get("last_seen")
        return last_seen is not None and (time.monotonic() - last_seen) < STALE_AFTER

    def value(self, key: str, default: Any = None) -> Any:
        """Прочитать поле телеметрии."""
        return self.data.get(key, default)

    def read(self, field: str, stage: int | None = None, default: Any = None) -> Any:
        """Прочитать поле телеметрии, при необходимости — по номеру ступени."""
        if stage is not None:
            return self.stage_value(field, stage, default)
        return self.value(field, default)

    def stage_value(self, key: str, stage: int, default: Any = None) -> Any:
        """Прочитать поле-массив по номеру ступени (1..5)."""
        values = self.data.get(key)
        if not isinstance(values, list) or len(values) < stage:
            return default
        return values[stage - 1]

    # ------------------------------------------------------------ жизненный цикл
    async def async_start(self) -> None:
        """Подключиться к устройству и запустить фоновые задачи."""
        await self._async_connect()
        assert self.config_entry is not None
        self._time_sync_task = self.config_entry.async_create_background_task(
            self.hass, self._time_sync_loop(), f"{DOMAIN}-time-sync"
        )

    async def async_stop(self) -> None:
        """Закрыть соединение и остановить фоновые задачи."""
        self._closing = True
        for task in (self._reconnect_task, self._time_sync_task):
            if task is not None and not task.done():
                task.cancel()
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as err:  # noqa: BLE001 - разрыв соединения не критичен
                _LOGGER.debug("Ошибка при отключении: %s", err)
            self._client = None

    def _ble_device(self) -> BLEDevice:
        """Найти устройство среди видимых адаптеру."""
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise UpdateFailed(
                f"Устройство Smart Osmos {self.address} не в зоне действия адаптера"
            )
        return device

    async def _async_connect(self) -> None:
        """Установить соединение, подписаться на уведомления и свериться по часам."""
        async with self._connect_lock:
            if self.connected or self._closing:
                return
            _LOGGER.debug("Подключаюсь к %s", self.address)
            client = await establish_connection(
                BleakClient,
                self._ble_device(),
                self.address,
                disconnected_callback=self._on_disconnected,
                max_attempts=4,
            )
            self._client = client
            for uuid in (CHAR_EXT_UUID, CHAR_EXT_CONFIG_UUID):
                await client.start_notify(uuid, self._on_notify)
                # Читаем сразу, чтобы сущности ожили, не дожидаясь уведомления.
                await self._async_read(uuid)
            await self._async_sync_time()
            _LOGGER.info("Smart Osmos %s: соединение установлено", self.address)

    def _on_disconnected(self, _client: BleakClient) -> None:
        """Отреагировать на разрыв соединения."""
        if self._closing:
            return
        _LOGGER.warning("Smart Osmos %s: соединение потеряно", self.address)
        self._client = None
        self.async_update_listeners()
        if self._reconnect_task is None or self._reconnect_task.done():
            assert self.config_entry is not None
            self._reconnect_task = self.config_entry.async_create_background_task(
                self.hass, self._reconnect_loop(), f"{DOMAIN}-reconnect"
            )

    async def _reconnect_loop(self) -> None:
        """Переподключаться, пока не получится."""
        while not self._closing and not self.connected:
            await asyncio.sleep(RECONNECT_DELAY)
            if self._closing:
                return
            try:
                await self._async_connect()
            except Exception as err:  # noqa: BLE001 - просто пробуем снова
                _LOGGER.debug("Переподключение не удалось: %s", err)

    async def _time_sync_loop(self) -> None:
        """Периодически отдавать устройству время Home Assistant."""
        while not self._closing:
            await asyncio.sleep(TIME_SYNC_INTERVAL)
            if not self.connected:
                continue
            try:
                await self._async_sync_time()
            except Exception as err:  # noqa: BLE001 - повторим через час
                _LOGGER.debug("Синхронизация времени не удалась: %s", err)

    async def _async_sync_time(self) -> None:
        """Отправить текущее время и смещение часового пояса.

        Именно отсюда контроллер узнаёт дату — её он потом показывает на экране
        замены фильтров.
        """
        now = dt_util.now()
        offset = now.utcoffset()
        await self.async_send_command(
            {
                "key": "time",
                "ts": int(now.timestamp()),
                "tz": int(offset.total_seconds() // 60) if offset else 0,
            }
        )

    # --------------------------------------------------------------- обмен
    def _on_notify(self, _sender: Any, payload: bytearray) -> None:
        """Принять уведомление от устройства."""
        self._ingest(payload)

    def _ingest(self, payload: bytes | bytearray) -> None:
        """Разобрать JSON и раздать его сущностям."""
        if not payload:
            return
        try:
            message = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as err:
            _LOGGER.debug("Нечитаемый пакет от %s: %s", self.address, err)
            return
        if not isinstance(message, dict):
            return
        # Телеметрия и конфигурация приходят разными пакетами и накапливаются
        # в одном словаре, поэтому обновляем его, а не заменяем.
        self.data.update(message)
        self.data["last_seen"] = time.monotonic()
        self.async_set_updated_data(self.data)

    async def _async_read(self, uuid: str) -> None:
        """Прочитать характеристику; пустой ответ до первой рассылки — норма."""
        if self._client is None:
            return
        try:
            self._ingest(await self._client.read_gatt_char(uuid))
        except Exception as err:  # noqa: BLE001 - дождёмся уведомления
            _LOGGER.debug("Не удалось прочитать %s: %s", uuid, err)

    async def async_refresh_config(self) -> None:
        """Перечитать характеристику конфигурации.

        Вызывается сразу после записи настройки, чтобы Home Assistant не ждал
        очередной рассылки — она приходит раз в 30 с.
        """
        if self.connected:
            await self._async_read(CHAR_EXT_CONFIG_UUID)

    async def async_send_command(self, payload: dict[str, Any]) -> None:
        """Записать команду в характеристику приложения."""
        async with self._write_lock:
            if not self.connected:
                raise HomeAssistantError(
                    f"Smart Osmos {self.address}: нет соединения с устройством"
                )
            assert self._client is not None
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            await self._client.write_gatt_char(CHAR_APP_UUID, data, response=True)
            _LOGGER.debug("Отправлено %s", payload)
