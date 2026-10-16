#pragma once

#include "esphome/core/component.h"
#include "esphome/core/helpers.h"
#include "esphome/core/preferences.h"

#include "flash_ring.h"

#ifdef USE_DISPLAY
#include "esphome/components/display/display.h"
#endif

#include <memory>
#include <string>
#include <vector>

namespace esphome {
namespace smart_osmos {

/// Количество ступеней очистки классического бытового осмоса.
static const uint8_t OSMOS_STAGES = 5;

/// Магия структуры настроек. Меняется при несовместимом изменении OsmosPrefs.
static const uint32_t OSMOS_PREF_MAGIC = 0x534F4D33;  // "SOM3"
/// Прошлая версия структуры: та же раскладка, но таймаут дисплея в минутах.
static const uint32_t OSMOS_PREF_MAGIC_V2 = 0x534F4D32;  // "SOM2"

/// Откуда ступень берёт объём: до мембраны (водопровод) или после (пермеат).
enum StageSource : uint8_t {
  STAGE_SRC_INLET = 0,
  STAGE_SRC_PERMEATE = 1,
};

/// Состояние ступени для отрисовки шкалы ресурса.
enum StageLevel : uint8_t {
  STAGE_LEVEL_OK = 0,       ///< > 20 %  — обычная шкала
  STAGE_LEVEL_LOW = 1,      ///< < 20 %  — мигает 0.25 Гц
  STAGE_LEVEL_CRITICAL = 2, ///< < 5 %   — мигает 0.5 Гц, шкала пустая и перечёркнута
  STAGE_LEVEL_DEAD = 3,     ///< = 0 %   — не мигает, шкала перечёркнута крест-накрест
};

/// Общее состояние установки — по нему выбирается цвет статусного светодиода.
enum Health : uint8_t {
  HEALTH_OK = 0,         ///< всё хорошо — зелёный
  HEALTH_LOW = 1,        ///< ресурс какой-то ступени на исходе — жёлтый
  HEALTH_BAD = 2,        ///< ресурс исчерпан или TDS выше порога — красный
  HEALTH_TDS_FAULT = 3,  ///< TDS-модуль не отвечает — белый
};

/// Всё, что переживает перезагрузку. Обычная (не packed) структура: на RISC-V
/// выравнивание важнее пары сэкономленных байт.
struct OsmosPrefs {
  uint32_t magic;

  float total_in;   ///< литров прошло через входной расходомер за всё время
  float total_out;  ///< литров прошло через выходной расходомер за всё время

  float stage_used[OSMOS_STAGES];      ///< литров с момента последней замены
  uint32_t stage_limit[OSMOS_STAGES];  ///< ресурс ступени в литрах (0 = не задан)
  uint32_t stage_date[OSMOS_STAGES];   ///< unix-время последней замены (0 = неизвестно)
  uint8_t stage_source[OSMOS_STAGES];  ///< StageSource

  float coeff_in;   ///< импульсов на литр, водопровод
  float coeff_out;  ///< импульсов на литр, чистая

  float tds_factor;  ///< калибровочный множитель TDS
  float tds_offset;  ///< калибровочное смещение TDS, ppm

  int16_t tz_offset_min;        ///< смещение часового пояса в минутах (из Home Assistant)
  uint16_t display_timeout_s;   ///< таймаут гашения дисплея, секунд

  float tds_day_min;
  float tds_day_max;
  float tds_day_sum;
  uint32_t tds_day_count;
  uint32_t tds_day_index;  ///< номер суток, для которых накоплена статистика
};

class SmartOsmos : public PollingComponent {
 public:
  SmartOsmos() : PollingComponent(1000) {}

  void setup() override;
  void loop() override;
  void update() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::LATE; }

  // ---------------------------------------------------------------- настройка
  void set_default_coeff_in(float v) { this->def_coeff_in_ = v; }
  void set_default_coeff_out(float v) { this->def_coeff_out_ = v; }
  void set_default_tds_factor(float v) { this->def_tds_factor_ = v; }
  void set_default_tds_offset(float v) { this->def_tds_offset_ = v; }
  void set_default_display_timeout(uint16_t seconds) { this->def_display_timeout_ = seconds; }
  void set_default_stage(uint8_t i, uint32_t limit, uint8_t source);
  void set_ota_password(const std::string &p) { this->ota_password_ = p; }
  void set_local_mtu(uint16_t mtu) { this->local_mtu_ = mtu; }
  void set_flow_window(uint32_t ms) { this->flow_window_ms_ = ms; }
  void set_firmware_version(const std::string &v) { this->firmware_version_ = v; }
  void set_storage_partition(const std::string &label) { this->storage_label_ = label; }
  void set_tds_high_ppm(float ppm) { this->tds_high_ppm_ = ppm; }
  void set_tds_fault_voltage(float min_v, float max_v) {
    this->tds_fault_min_v_ = min_v;
    this->tds_fault_max_v_ = max_v;
  }
  void set_tds_fault_delay(uint32_t ms) { this->tds_fault_delay_ms_ = ms; }

  // ------------------------------------------------------------------- вход
  /// Добавить импульсы входного (водопровод) расходомера.
  void add_pulses_in(uint32_t pulses);
  /// Добавить импульсы выходного (чистая вода) расходомера.
  void add_pulses_out(uint32_t pulses);
  /// Напряжение с TDS-датчика, вольты.
  void set_tds_voltage(float volts);
  /// Температура воды для термокомпенсации, °C.
  void set_water_temp(float celsius) { this->water_temp_ = celsius; }

  // ------------------------------------------------------------------ выход
  float tds() const { return this->tds_; }
  float tds_voltage() const { return this->tds_voltage_; }
  float tds_day_avg() const;
  float tds_day_min() const;
  float tds_day_max() const;

  float flow_in() const { return this->flow_in_; }    ///< л/мин, водопровод
  float flow_out() const { return this->flow_out_; }  ///< л/мин, чистая
  float minute_in() const;                            ///< литров за последнюю минуту
  float minute_out() const;

  float total_in() const { return this->prefs_.total_in; }
  float total_out() const { return this->prefs_.total_out; }

  float stage_used(uint8_t i) const;
  uint32_t stage_limit(uint8_t i) const;
  /// Остаток ресурса ступени, 0..100 %. При limit == 0 возвращает 100.
  float stage_remaining(uint8_t i) const;
  /// Использовано ресурса, 0..100 % — в таком виде его ждёт мобильное приложение.
  int stage_used_pct(uint8_t i) const;
  StageLevel stage_level(uint8_t i) const;
  uint32_t stage_date(uint8_t i) const;
  std::string stage_date_str(uint8_t i) const;

  /// Коэффициент прочистки: доля чистой воды от водопроводной, %.
  float purification_ratio() const;

  /// TDS-модуль не отвечает: напряжение вне рабочего диапазона дольше
  /// tds_fault_delay либо датчик давно не присылал измерений.
  bool tds_fault() const;
  /// Сводное состояние для светодиода (без учёта идущей прошивки).
  Health health() const;
  const std::string &firmware_version() const { return this->firmware_version_; }
  /// true — состояние хранится в отдельном разделе с распределением износа,
  /// false — по старинке в NVS (раздела нет в таблице разделов).
  bool storage_is_ring() const { return this->ring_.ready(); }
  /// Эффективность по формуле исходного проекта: 100 - out*100/in.
  float efficiency() const;

  // --------------------------------------------------------------- управление
  void set_stage_limit(uint8_t i, uint32_t liters);
  void set_stage_source(uint8_t i, uint8_t source);
  void reset_stage(uint8_t i);
  void reset_totals();
  void reset_day_stats();

  float coeff_in() const { return this->prefs_.coeff_in; }
  float coeff_out() const { return this->prefs_.coeff_out; }
  void set_coeff_in(float v);
  void set_coeff_out(float v);

  float tds_factor() const { return this->prefs_.tds_factor; }
  void set_tds_factor(float v);
  float tds_offset() const { return this->prefs_.tds_offset; }
  void set_tds_offset(float v);

  uint16_t display_timeout_s() const { return this->prefs_.display_timeout_s; }
  void set_display_timeout_s(uint16_t seconds);

  // --------------------------------------------------- калибровка «на 1 литр»
  /// Запустить калибровку выходного (чистого) расходомера.
  void calibration_start();
  /// Завершить калибровку: через расходомер прошёл ровно `liters` литров.
  void calibration_finish(float liters = 1.0f);
  void calibration_cancel();
  bool calibrating() const { return this->calib_active_; }
  uint32_t calibration_pulses() const { return this->calib_pulses_; }

  // ------------------------------------------------------------------- время
  /// Установить текущее unix-время (приходит от приложения или Home Assistant).
  void set_epoch(uint32_t epoch);
  void set_tz_offset_min(int16_t minutes);
  int16_t tz_offset_min() const { return this->prefs_.tz_offset_min; }
  bool time_valid() const { return this->epoch_base_ != 0; }
  uint32_t now_epoch() const;
  std::string format_date(uint32_t epoch) const;
  std::string uptime_str() const;

  // -------------------------------------------------------------- BLE-протокол
  /// Разбор команды от мобильного приложения / Home Assistant.
  void handle_command(const std::string &payload);
  /// Полезная нагрузка ключа "real_time".
  std::string realtime_json();
  std::vector<uint8_t> realtime_bytes() { return this->to_bytes_(this->realtime_json()); }
  /// Полезная нагрузка ключа "config_data".
  std::string config_json();
  std::vector<uint8_t> config_bytes() { return this->to_bytes_(this->config_json()); }
  /// Расширенная телеметрия для интеграции Home Assistant (ключ "ext").
  std::string ext_json();
  std::vector<uint8_t> ext_bytes() { return this->to_bytes_(this->ext_json()); }
  /// Расширенная конфигурация: ресурсы, даты замены, калибровки (ключ "ext_config").
  std::string ext_config_json();
  std::vector<uint8_t> ext_config_bytes() { return this->to_bytes_(this->ext_config_json()); }
  /// Приложение включает поток данных командой {"key":"get_data","en":"On"}.
  bool stream_enabled() const { return this->stream_enabled_; }
  /// true, если в ответ на разобранную команду нужно отправить config_data.
  bool take_config_request();
  bool ota_enabled() const { return this->ota_enabled_; }

  void save();

 protected:
  std::vector<uint8_t> to_bytes_(const std::string &s) const { return std::vector<uint8_t>(s.begin(), s.end()); }
  void load_defaults_();
  void roll_day_(uint32_t day_index);
  uint32_t current_day_() const;
  void add_volume_(float liters_in, float liters_out);
  void apply_mtu_();
  void open_storage_();
  void migrate_from_v2_();
  void remember_saved_volume_();

  // Хранилище: кольцевой журнал в разделе flash, а если раздела нет — NVS.
  std::unique_ptr<FlashIO> ring_io_;
  FlashRing ring_;
  std::string storage_label_{"osmos"};
  // Объём на момент последнего сохранения, в целых литрах.
  uint32_t saved_liters_in_{0};
  uint32_t saved_liters_out_{0};
  uint32_t saved_tds_count_{0};
  uint32_t last_stats_save_{0};

  std::string firmware_version_{"dev"};

  // Диагностика TDS-модуля.
  float tds_high_ppm_{100.0f};
  float tds_fault_min_v_{0.01f};
  float tds_fault_max_v_{2.5f};
  uint32_t tds_fault_delay_ms_{60000};
  uint32_t tds_out_of_range_since_{0};
  uint32_t tds_last_update_{0};
  bool tds_seen_{false};

  ESPPreferenceObject pref_;
  OsmosPrefs prefs_{};

  // значения по умолчанию из YAML
  float def_coeff_in_{5880.0f};
  float def_coeff_out_{5880.0f};
  float def_tds_factor_{1.0f};
  float def_tds_offset_{0.0f};
  uint16_t def_display_timeout_{30};
  uint32_t def_stage_limit_[OSMOS_STAGES]{6000, 6000, 6000, 5000, 3000};
  uint8_t def_stage_source_[OSMOS_STAGES]{STAGE_SRC_INLET, STAGE_SRC_INLET, STAGE_SRC_INLET, STAGE_SRC_INLET,
                                          STAGE_SRC_PERMEATE};

  // накопление импульсов между тиками update()
  uint32_t pulses_in_acc_{0};
  uint32_t pulses_out_acc_{0};

  float flow_in_{0.0f};
  float flow_out_{0.0f};
  uint32_t flow_window_ms_{5000};
  uint32_t flow_window_start_{0};
  uint32_t flow_window_pulses_in_{0};
  uint32_t flow_window_pulses_out_{0};

  // кольцевой буфер расхода за последние 60 секунд
  static const uint8_t MINUTE_SLOTS = 60;
  float minute_in_[MINUTE_SLOTS]{};
  float minute_out_[MINUTE_SLOTS]{};
  uint8_t minute_pos_{0};

  float tds_{0.0f};
  float tds_voltage_{0.0f};
  float water_temp_{25.0f};

  bool calib_active_{false};
  uint32_t calib_pulses_{0};

  uint32_t epoch_base_{0};
  uint32_t epoch_millis_{0};

  bool stream_enabled_{false};
  bool config_requested_{false};
  bool ota_enabled_{false};
  std::string ota_password_{"OeN12345"};

  uint16_t local_mtu_{512};
  bool mtu_done_{false};
  uint32_t mtu_next_try_{0};
  uint8_t mtu_tries_{0};

};

#ifdef USE_DISPLAY
/// Рисует шкалу ресурса ступени с учётом её состояния и фазы мигания.
/// Возвращает false, если в текущей фазе мигания элемент рисовать не нужно —
/// вызывающий код по этому же признаку гасит и цифру ступени.
bool draw_stage_bar(display::Display *it, int x, int y, int w, int h, float remaining_pct, StageLevel level,
                    uint32_t now_ms);
/// Видима ли ступень в текущей фазе мигания (для цифры над шкалой).
bool stage_visible(StageLevel level, uint32_t now_ms);
#endif

}  // namespace smart_osmos
}  // namespace esphome
