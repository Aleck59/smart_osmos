"""Ядро контроллера обратного осмоса Smart Osmos.

Компонент хранит всё состояние установки (объёмы, ресурс ступеней, статистику
TDS, калибровки), считает расход по импульсам расходомеров и говорит на
JSON-протоколе мобильного приложения VGCH/smart_osmos поверх BLE.
"""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_SOURCE

CODEOWNERS = ["@Aleck59"]
MULTI_CONF = False

smart_osmos_ns = cg.esphome_ns.namespace("smart_osmos")
SmartOsmos = smart_osmos_ns.class_("SmartOsmos", cg.PollingComponent)

CONF_PULSES_PER_LITER_IN = "pulses_per_liter_in"
CONF_PULSES_PER_LITER_OUT = "pulses_per_liter_out"
CONF_TDS_FACTOR = "tds_factor"
CONF_TDS_OFFSET = "tds_offset"
CONF_DISPLAY_TIMEOUT = "display_timeout"
CONF_LOCAL_MTU = "local_mtu"
CONF_FLOW_WINDOW = "flow_window"
CONF_OTA_PASSWORD = "ota_password"
CONF_STAGES = "stages"
CONF_LIMIT = "limit"
CONF_FIRMWARE_VERSION = "firmware_version"
CONF_STORAGE_PARTITION = "storage_partition"
CONF_TDS_HIGH = "tds_high"
CONF_TDS_FAULT_MIN_VOLTAGE = "tds_fault_min_voltage"
CONF_TDS_FAULT_MAX_VOLTAGE = "tds_fault_max_voltage"
CONF_TDS_FAULT_DELAY = "tds_fault_delay"

STAGE_SOURCES = {
    "inlet": 0,  # объём считается по входному расходомеру (водопровод)
    "permeate": 1,  # объём считается по выходному расходомеру (чистая вода)
}

# Классический бытовой осмос: три предфильтра, мембрана, постфильтр.
DEFAULT_STAGES = [
    {CONF_LIMIT: 6000, CONF_SOURCE: "inlet"},
    {CONF_LIMIT: 6000, CONF_SOURCE: "inlet"},
    {CONF_LIMIT: 6000, CONF_SOURCE: "inlet"},
    {CONF_LIMIT: 5000, CONF_SOURCE: "inlet"},
    {CONF_LIMIT: 3000, CONF_SOURCE: "permeate"},
]

STAGE_SCHEMA = cv.Schema(
    {
        cv.Required(CONF_LIMIT): cv.positive_int,
        cv.Optional(CONF_SOURCE, default="inlet"): cv.enum(STAGE_SOURCES, lower=True),
    }
)


def _exactly_five(value):
    value = cv.ensure_list(STAGE_SCHEMA)(value)
    if len(value) != 5:
        raise cv.Invalid(
            f"У осмоса должно быть описано ровно 5 ступеней, указано {len(value)}"
        )
    return value


CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(SmartOsmos),
        cv.Optional(CONF_PULSES_PER_LITER_IN, default=5880): cv.positive_not_null_int,
        cv.Optional(CONF_PULSES_PER_LITER_OUT, default=5880): cv.positive_not_null_int,
        cv.Optional(CONF_TDS_FACTOR, default=1.0): cv.positive_float,
        cv.Optional(CONF_TDS_OFFSET, default=0.0): cv.float_,
        cv.Optional(CONF_DISPLAY_TIMEOUT, default="10min"): cv.All(
            cv.positive_time_period_minutes,
            cv.Range(min=cv.TimePeriod(minutes=1), max=cv.TimePeriod(minutes=1440)),
        ),
        cv.Optional(CONF_FLOW_WINDOW, default="5s"): cv.All(
            cv.positive_time_period_milliseconds,
            cv.Range(min=cv.TimePeriod(seconds=1), max=cv.TimePeriod(seconds=60)),
        ),
        cv.Optional(CONF_LOCAL_MTU, default=512): cv.int_range(min=23, max=517),
        cv.Optional(CONF_OTA_PASSWORD, default="OeN12345"): cv.string,
        cv.Optional(CONF_STAGES, default=DEFAULT_STAGES): _exactly_five,
        cv.Optional(CONF_FIRMWARE_VERSION, default="dev"): cv.string_strict,
        # Раздел data с подтипом 0x40 под журнал состояния (см. partitions.csv).
        # Если его нет в таблице разделов, состояние хранится в NVS.
        cv.Optional(CONF_STORAGE_PARTITION, default="osmos"): cv.string_strict,
        # Выше этого порога TDS светодиод загорается красным.
        cv.Optional(CONF_TDS_HIGH, default=100.0): cv.positive_float,
        # TDS-модуль считается неисправным, если его напряжение дольше
        # tds_fault_delay держится вне этого диапазона.
        cv.Optional(CONF_TDS_FAULT_MIN_VOLTAGE, default=0.01): cv.float_range(min=0, max=3.3),
        cv.Optional(CONF_TDS_FAULT_MAX_VOLTAGE, default=2.5): cv.float_range(min=0, max=3.3),
        cv.Optional(CONF_TDS_FAULT_DELAY, default="60s"): cv.positive_time_period_milliseconds,
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)

    cg.add(var.set_default_coeff_in(config[CONF_PULSES_PER_LITER_IN]))
    cg.add(var.set_default_coeff_out(config[CONF_PULSES_PER_LITER_OUT]))
    cg.add(var.set_default_tds_factor(config[CONF_TDS_FACTOR]))
    cg.add(var.set_default_tds_offset(config[CONF_TDS_OFFSET]))
    cg.add(var.set_default_display_timeout(int(config[CONF_DISPLAY_TIMEOUT].total_minutes)))
    cg.add(var.set_flow_window(int(config[CONF_FLOW_WINDOW].total_milliseconds)))
    cg.add(var.set_local_mtu(config[CONF_LOCAL_MTU]))
    cg.add(var.set_ota_password(config[CONF_OTA_PASSWORD]))

    cg.add(var.set_firmware_version(config[CONF_FIRMWARE_VERSION]))
    cg.add(var.set_storage_partition(config[CONF_STORAGE_PARTITION]))
    cg.add(var.set_tds_high_ppm(config[CONF_TDS_HIGH]))
    cg.add(
        var.set_tds_fault_voltage(
            config[CONF_TDS_FAULT_MIN_VOLTAGE], config[CONF_TDS_FAULT_MAX_VOLTAGE]
        )
    )
    cg.add(var.set_tds_fault_delay(int(config[CONF_TDS_FAULT_DELAY].total_milliseconds)))

    for index, stage in enumerate(config[CONF_STAGES]):
        cg.add(var.set_default_stage(index, stage[CONF_LIMIT], stage[CONF_SOURCE]))
