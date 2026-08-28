"""Константы интеграции Smart Osmos."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "smart_osmos"

# Имя, которым устройство представляется в эфире.
DEFAULT_LOCAL_NAME: Final = "SMART OSMOS"

# --- GATT ---------------------------------------------------------------------
# Сервис и первая характеристика совпадают с исходной прошивкой VGCH/smart_osmos,
# поэтому мобильное приложение и эта интеграция говорят на одном языке.
SERVICE_UUID: Final = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
CHAR_APP_UUID: Final = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
CHAR_EXT_UUID: Final = "beb5483e-36e1-4688-b7f5-ea07361b26a9"
CHAR_EXT_CONFIG_UUID: Final = "beb5483e-36e1-4688-b7f5-ea07361b26aa"

# --- Ступени ------------------------------------------------------------------
STAGE_COUNT: Final = 5
STAGE_NAMES: Final = {
    1: "Механическая очистка",
    2: "Уголь GAC",
    3: "Уголь CTO",
    4: "Мембрана RO",
    5: "Постфильтр",
}

# --- Поведение ----------------------------------------------------------------
# Как часто отправлять устройству текущее время Home Assistant.
TIME_SYNC_INTERVAL: Final = 3600
# Данные считаются устаревшими, если их не было дольше этого срока.
STALE_AFTER: Final = 120
# Пауза перед повторным подключением после разрыва.
RECONNECT_DELAY: Final = 10
