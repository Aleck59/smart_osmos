#include "smart_osmos.h"

#include "esphome/core/log.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>

// esp_ble_gatt_set_local_mtu() живёт в Bluedroid; sdkconfig-флаг выставляет
// сам компонент esp32_ble, поэтому проверяем именно его.
#ifdef USE_ESP32
#include <esp_partition.h>
#endif

#if defined(USE_ESP32) && defined(CONFIG_BT_BLUEDROID_ENABLED)
#define OSMOS_HAS_BLUEDROID
#include <esp_gatt_common_api.h>
#endif

namespace esphome {
namespace smart_osmos {

static const char *const TAG = "smart_osmos";

/// Суточная статистика TDS меняется каждые 2 с; во flash её кладём раз в час.
static const uint32_t STATS_SAVE_INTERVAL_MS = 60 * 60 * 1000UL;

/// Пользовательский подтип раздела данных под журнал состояния.
static const uint8_t STORAGE_PARTITION_SUBTYPE = 0x40;

#ifdef USE_ESP32
/// Раздел flash как поверхность для кольцевого журнала.
class EspPartitionIO : public FlashIO {
 public:
  explicit EspPartitionIO(const esp_partition_t *part) : part_(part) {}
  size_t size() const override { return this->part_->size; }
  bool read(size_t offset, void *dst, size_t len) override {
    return esp_partition_read(this->part_, offset, dst, len) == ESP_OK;
  }
  bool write(size_t offset, const void *src, size_t len) override {
    return esp_partition_write(this->part_, offset, src, len) == ESP_OK;
  }
  bool erase_sector(size_t offset) override {
    return esp_partition_erase_range(this->part_, offset, this->sector_size()) == ESP_OK;
  }

 protected:
  const esp_partition_t *part_;
};
#endif

// ---------------------------------------------------------------------------
// Мини-парсер плоского JSON.
//
// Протокол приложения — это всегда плоский объект из строк и чисел, поэтому
// полноценный разбор здесь не нужен, а отказ от ArduinoJson убирает зависимость
// от версии API и экономит несколько килобайт.
// ---------------------------------------------------------------------------
static bool json_field(const std::string &s, const char *name, std::string &out) {
  std::string key = std::string("\"") + name + "\"";
  size_t p = s.find(key);
  if (p == std::string::npos)
    return false;
  p = s.find(':', p + key.size());
  if (p == std::string::npos)
    return false;
  p++;
  while (p < s.size() && std::isspace(static_cast<unsigned char>(s[p])))
    p++;
  if (p >= s.size())
    return false;

  out.clear();
  if (s[p] == '"') {
    p++;
    while (p < s.size() && s[p] != '"') {
      if (s[p] == '\\' && p + 1 < s.size())
        p++;
      out.push_back(s[p]);
      p++;
    }
    return true;
  }
  while (p < s.size() && s[p] != ',' && s[p] != '}' && !std::isspace(static_cast<unsigned char>(s[p]))) {
    out.push_back(s[p]);
    p++;
  }
  return !out.empty();
}

static bool json_field_float(const std::string &s, const char *name, float &out) {
  std::string raw;
  if (!json_field(s, name, raw))
    return false;
  char *end = nullptr;
  float v = strtof(raw.c_str(), &end);
  if (end == raw.c_str())
    return false;
  out = v;
  return true;
}

static bool json_field_u32(const std::string &s, const char *name, uint32_t &out) {
  float v;
  if (!json_field_float(s, name, v))
    return false;
  if (v < 0)
    v = 0;
  out = static_cast<uint32_t>(v);
  return true;
}

// -------------------------------------------------------- сборка JSON-ответов
static void json_kv_str(std::string &j, const char *k, const std::string &v, bool first = false) {
  if (!first)
    j += ',';
  j += '"';
  j += k;
  j += "\":\"";
  for (char c : v) {
    if (c == '"' || c == '\\')
      j += '\\';
    j += c;
  }
  j += '"';
}

static void json_kv_raw(std::string &j, const char *k, const std::string &v, bool first = false) {
  if (!first)
    j += ',';
  j += '"';
  j += k;
  j += "\":";
  j += v;
}

static std::string fmt(const char *format, float value) {
  char buf[24];
  snprintf(buf, sizeof(buf), format, value);
  return std::string(buf);
}

static std::string itos(long v) {
  char buf[16];
  snprintf(buf, sizeof(buf), "%ld", v);
  return std::string(buf);
}

// ---------------------------------------------------------------------------
// Жизненный цикл
// ---------------------------------------------------------------------------
void SmartOsmos::set_default_stage(uint8_t i, uint32_t limit, uint8_t source) {
  if (i >= OSMOS_STAGES)
    return;
  this->def_stage_limit_[i] = limit;
  this->def_stage_source_[i] = source;
}

void SmartOsmos::load_defaults_() {
  memset(&this->prefs_, 0, sizeof(this->prefs_));
  this->prefs_.magic = OSMOS_PREF_MAGIC;
  this->prefs_.coeff_in = this->def_coeff_in_;
  this->prefs_.coeff_out = this->def_coeff_out_;
  this->prefs_.tds_factor = this->def_tds_factor_;
  this->prefs_.tds_offset = this->def_tds_offset_;
  this->prefs_.display_timeout_min = this->def_display_timeout_;
  this->prefs_.tds_day_min = NAN;
  this->prefs_.tds_day_max = NAN;
  for (uint8_t i = 0; i < OSMOS_STAGES; i++) {
    this->prefs_.stage_limit[i] = this->def_stage_limit_[i];
    this->prefs_.stage_source[i] = this->def_stage_source_[i];
  }
}

void SmartOsmos::open_storage_() {
#ifdef USE_ESP32
  const esp_partition_t *part =
      esp_partition_find_first(ESP_PARTITION_TYPE_DATA, static_cast<esp_partition_subtype_t>(STORAGE_PARTITION_SUBTYPE),
                               this->storage_label_.c_str());
  if (part == nullptr) {
    ESP_LOGW(TAG,
             "Раздела «%s» в таблице разделов нет — состояние хранится в NVS. "
             "Чтобы включить журнал с распределением износа, прошейте устройство один раз по USB.",
             this->storage_label_.c_str());
    return;
  }
  this->ring_io_ = std::make_unique<EspPartitionIO>(part);
  if (!this->ring_.begin(this->ring_io_.get(), sizeof(OsmosPrefs))) {
    ESP_LOGE(TAG, "Раздел «%s» слишком мал для журнала", this->storage_label_.c_str());
    this->ring_io_.reset();
  }
#endif
}

void SmartOsmos::setup() {
  // Старое место хранения: оно же источник для переезда в журнал.
  this->pref_ = global_preferences->make_preference<OsmosPrefs>(fnv1_hash("smart_osmos_state"));
  this->open_storage_();

  bool loaded = false;
  if (this->ring_.ready() && this->ring_.load(&this->prefs_) && this->prefs_.magic == OSMOS_PREF_MAGIC) {
    loaded = true;
    ESP_LOGI(TAG, "Состояние прочитано из журнала, запись №%u", this->ring_.sequence());
  } else if (this->pref_.load(&this->prefs_) && this->prefs_.magic == OSMOS_PREF_MAGIC) {
    loaded = true;
    if (this->ring_.ready()) {
      // Первый запуск с журналом: переносим состояние из NVS без потерь.
      ESP_LOGI(TAG, "Перенос состояния из NVS в журнал");
      this->ring_.append(&this->prefs_);
    }
  }
  if (!loaded) {
    ESP_LOGI(TAG, "Сохранённого состояния нет — применяю значения по умолчанию");
    this->load_defaults_();
    this->save();
  }
  // Защита от нулевых коэффициентов: деление на них происходит каждую секунду.
  if (!(this->prefs_.coeff_in > 0))
    this->prefs_.coeff_in = this->def_coeff_in_;
  if (!(this->prefs_.coeff_out > 0))
    this->prefs_.coeff_out = this->def_coeff_out_;
  if (this->prefs_.display_timeout_min == 0)
    this->prefs_.display_timeout_min = this->def_display_timeout_;

  this->flow_window_start_ = millis();
  this->last_stats_save_ = millis();
  this->saved_tds_count_ = this->prefs_.tds_day_count;
  this->remember_saved_volume_();
}

void SmartOsmos::remember_saved_volume_() {
  this->saved_liters_in_ = static_cast<uint32_t>(this->prefs_.total_in);
  this->saved_liters_out_ = static_cast<uint32_t>(this->prefs_.total_out);
}

void SmartOsmos::apply_mtu_() {
#ifdef OSMOS_HAS_BLUEDROID
  // ESPHome не поднимает локальный MTU, а мобильное приложение ждёт JSON одним
  // уведомлением. Bluedroid принимает вызов только после включения стека,
  // поэтому пробуем повторно, пока не получится.
  if (this->mtu_done_ || this->mtu_tries_ > 30)
    return;
  const uint32_t now = millis();
  if (now < this->mtu_next_try_)
    return;
  this->mtu_next_try_ = now + 1000;
  this->mtu_tries_++;
  esp_err_t err = esp_ble_gatt_set_local_mtu(this->local_mtu_);
  if (err == ESP_OK) {
    this->mtu_done_ = true;
    ESP_LOGI(TAG, "Локальный BLE MTU установлен в %u", this->local_mtu_);
  } else if (this->mtu_tries_ == 30) {
    ESP_LOGW(TAG, "Не удалось поднять BLE MTU (%d); длинные уведомления будут обрезаны", err);
  }
#endif
}

void SmartOsmos::loop() { this->apply_mtu_(); }

void SmartOsmos::dump_config() {
  ESP_LOGCONFIG(TAG, "Smart Osmos %s:", this->firmware_version_.c_str());
  if (this->ring_.ready()) {
    ESP_LOGCONFIG(TAG, "  Хранилище: журнал «%s», %u слотов по %u Б, последняя запись №%u",
                  this->storage_label_.c_str(), (unsigned) this->ring_.slot_count(),
                  (unsigned) this->ring_.slot_size(), this->ring_.sequence());
  } else {
    ESP_LOGCONFIG(TAG, "  Хранилище: NVS (раздела «%s» нет)", this->storage_label_.c_str());
  }
  ESP_LOGCONFIG(TAG, "  Импульсов на литр: водопровод %.0f, чистая %.0f", this->prefs_.coeff_in,
                this->prefs_.coeff_out);
  ESP_LOGCONFIG(TAG, "  Калибровка TDS: множитель %.3f, смещение %.1f ppm", this->prefs_.tds_factor,
                this->prefs_.tds_offset);
  for (uint8_t i = 0; i < OSMOS_STAGES; i++) {
    ESP_LOGCONFIG(TAG, "  Ступень %u: ресурс %u л, источник %s, израсходовано %.1f л", i + 1,
                  this->prefs_.stage_limit[i], this->prefs_.stage_source[i] == STAGE_SRC_PERMEATE ? "чистая" : "вход",
                  this->prefs_.stage_used[i]);
  }
}

// ---------------------------------------------------------------------------
// Импульсы и объёмы
// ---------------------------------------------------------------------------
void SmartOsmos::add_pulses_in(uint32_t pulses) {
  this->pulses_in_acc_ += pulses;
  this->flow_window_pulses_in_ += pulses;
}

void SmartOsmos::add_pulses_out(uint32_t pulses) {
  this->pulses_out_acc_ += pulses;
  this->flow_window_pulses_out_ += pulses;
  if (this->calib_active_)
    this->calib_pulses_ += pulses;
}

void SmartOsmos::add_volume_(float liters_in, float liters_out) {
  this->prefs_.total_in += liters_in;
  this->prefs_.total_out += liters_out;
  for (uint8_t i = 0; i < OSMOS_STAGES; i++) {
    this->prefs_.stage_used[i] += (this->prefs_.stage_source[i] == STAGE_SRC_PERMEATE) ? liters_out : liters_in;
  }
}

void SmartOsmos::update() {
  const uint32_t now = millis();

  // --- объём, накопленный за такт ---
  const float liters_in = this->pulses_in_acc_ / this->prefs_.coeff_in;
  const float liters_out = this->pulses_out_acc_ / this->prefs_.coeff_out;
  this->pulses_in_acc_ = 0;
  this->pulses_out_acc_ = 0;
  this->add_volume_(liters_in, liters_out);

  // --- расход за последнюю минуту (кольцевой буфер по секундам) ---
  this->minute_in_[this->minute_pos_] = liters_in;
  this->minute_out_[this->minute_pos_] = liters_out;
  this->minute_pos_ = (this->minute_pos_ + 1) % MINUTE_SLOTS;

  // --- мгновенный расход, усреднённый по окну ---
  const uint32_t elapsed = now - this->flow_window_start_;
  if (elapsed >= this->flow_window_ms_) {
    const float minutes = elapsed / 60000.0f;
    this->flow_in_ = (this->flow_window_pulses_in_ / this->prefs_.coeff_in) / minutes;
    this->flow_out_ = (this->flow_window_pulses_out_ / this->prefs_.coeff_out) / minutes;
    this->flow_window_pulses_in_ = 0;
    this->flow_window_pulses_out_ = 0;
    this->flow_window_start_ = now;
  }

  // --- суточная статистика TDS ---
  const uint32_t day = this->current_day_();
  if (day != this->prefs_.tds_day_index)
    this->roll_day_(day);

  // --- сохранение: объёмы — на каждом новом литре любой из линий ---
  if (static_cast<uint32_t>(this->prefs_.total_in) != this->saved_liters_in_ ||
      static_cast<uint32_t>(this->prefs_.total_out) != this->saved_liters_out_) {
    this->save();
  } else if (this->prefs_.tds_day_count != this->saved_tds_count_ &&
             (now - this->last_stats_save_) >= STATS_SAVE_INTERVAL_MS) {
    // Суточная статистика TDS — раз в час, если воды за это время не было.
    this->save();
  }
}

float SmartOsmos::minute_in() const {
  float sum = 0;
  for (uint8_t i = 0; i < MINUTE_SLOTS; i++)
    sum += this->minute_in_[i];
  return sum;
}

float SmartOsmos::minute_out() const {
  float sum = 0;
  for (uint8_t i = 0; i < MINUTE_SLOTS; i++)
    sum += this->minute_out_[i];
  return sum;
}

// ---------------------------------------------------------------------------
// TDS
// ---------------------------------------------------------------------------
void SmartOsmos::set_tds_voltage(float volts) {
  if (std::isnan(volts))
    return;
  this->tds_voltage_ = volts;

  const uint32_t now = millis();
  this->tds_seen_ = true;
  this->tds_last_update_ = now;
  if (volts < this->tds_fault_min_v_ || volts > this->tds_fault_max_v_) {
    if (this->tds_out_of_range_since_ == 0)
      this->tds_out_of_range_since_ = now | 1;  // 0 зарезервирован под «в норме»
  } else {
    this->tds_out_of_range_since_ = 0;
  }

  // Формула DFRobot TDS Meter с термокомпенсацией — та же, что в исходном проекте.
  const float t_coef = 1.0f + 0.02f * (this->water_temp_ - 25.0f);
  const float ec = volts / t_coef;
  float tds = (133.42f * ec * ec * ec - 255.86f * ec * ec + 857.39f * ec) * 0.5f;
  tds = tds * this->prefs_.tds_factor + this->prefs_.tds_offset;
  if (tds < 0)
    tds = 0;
  this->tds_ = tds;

  if (std::isnan(this->prefs_.tds_day_min) || tds < this->prefs_.tds_day_min)
    this->prefs_.tds_day_min = tds;
  if (std::isnan(this->prefs_.tds_day_max) || tds > this->prefs_.tds_day_max)
    this->prefs_.tds_day_max = tds;
  this->prefs_.tds_day_sum += tds;
  this->prefs_.tds_day_count++;
}

float SmartOsmos::tds_day_avg() const {
  if (this->prefs_.tds_day_count == 0)
    return NAN;
  return this->prefs_.tds_day_sum / this->prefs_.tds_day_count;
}

float SmartOsmos::tds_day_min() const { return this->prefs_.tds_day_min; }
float SmartOsmos::tds_day_max() const { return this->prefs_.tds_day_max; }

void SmartOsmos::roll_day_(uint32_t day_index) {
  this->prefs_.tds_day_index = day_index;
  this->prefs_.tds_day_min = NAN;
  this->prefs_.tds_day_max = NAN;
  this->prefs_.tds_day_sum = 0;
  this->prefs_.tds_day_count = 0;
  this->save();
}

void SmartOsmos::reset_day_stats() { this->roll_day_(this->current_day_()); }

uint32_t SmartOsmos::current_day_() const {
  if (this->time_valid()) {
    const int32_t local = static_cast<int32_t>(this->now_epoch()) + this->prefs_.tz_offset_min * 60;
    return static_cast<uint32_t>(local / 86400);
  }
  // Времени нет — считаем сутками от старта, со сдвигом, чтобы индекс не совпал
  // с настоящим номером дня после синхронизации.
  return 0x40000000u + millis() / 86400000UL;
}

// ---------------------------------------------------------------------------
// Ступени
// ---------------------------------------------------------------------------
float SmartOsmos::stage_used(uint8_t i) const { return i < OSMOS_STAGES ? this->prefs_.stage_used[i] : 0.0f; }
uint32_t SmartOsmos::stage_limit(uint8_t i) const { return i < OSMOS_STAGES ? this->prefs_.stage_limit[i] : 0; }
uint32_t SmartOsmos::stage_date(uint8_t i) const { return i < OSMOS_STAGES ? this->prefs_.stage_date[i] : 0; }
std::string SmartOsmos::stage_date_str(uint8_t i) const { return this->format_date(this->stage_date(i)); }

float SmartOsmos::stage_remaining(uint8_t i) const {
  if (i >= OSMOS_STAGES)
    return 0.0f;
  const uint32_t limit = this->prefs_.stage_limit[i];
  if (limit == 0)
    return 100.0f;  // ресурс не задан — считаем ступень полной
  const float left = 100.0f - (this->prefs_.stage_used[i] * 100.0f / limit);
  return clamp(left, 0.0f, 100.0f);
}

int SmartOsmos::stage_used_pct(uint8_t i) const {
  if (i >= OSMOS_STAGES)
    return 0;
  const uint32_t limit = this->prefs_.stage_limit[i];
  if (limit == 0)
    return 0;
  return static_cast<int>(this->prefs_.stage_used[i] * 100.0f / limit);
}

StageLevel SmartOsmos::stage_level(uint8_t i) const {
  const float left = this->stage_remaining(i);
  if (left <= 0.0f)
    return STAGE_LEVEL_DEAD;
  if (left < 5.0f)
    return STAGE_LEVEL_CRITICAL;
  if (left < 20.0f)
    return STAGE_LEVEL_LOW;
  return STAGE_LEVEL_OK;
}

void SmartOsmos::set_stage_limit(uint8_t i, uint32_t liters) {
  if (i >= OSMOS_STAGES || this->prefs_.stage_limit[i] == liters)
    return;
  this->prefs_.stage_limit[i] = liters;
  this->save();
}

void SmartOsmos::set_stage_source(uint8_t i, uint8_t source) {
  if (i >= OSMOS_STAGES || this->prefs_.stage_source[i] == source)
    return;
  this->prefs_.stage_source[i] = source;
  this->save();
}

void SmartOsmos::reset_stage(uint8_t i) {
  if (i >= OSMOS_STAGES)
    return;
  this->prefs_.stage_used[i] = 0;
  this->prefs_.stage_date[i] = this->time_valid() ? this->now_epoch() : 0;
  ESP_LOGI(TAG, "Ступень %u: ресурс сброшен", i + 1);
  this->save();
}

void SmartOsmos::reset_totals() {
  this->prefs_.total_in = 0;
  this->prefs_.total_out = 0;
  ESP_LOGI(TAG, "Суммарные счётчики обнулены");
  this->save();
}

bool SmartOsmos::tds_fault() const {
  const uint32_t now = millis();
  // Измерений нет вовсе или они давно прекратились.
  if (!this->tds_seen_)
    return now > this->tds_fault_delay_ms_;
  if (now - this->tds_last_update_ > this->tds_fault_delay_ms_)
    return true;
  // Напряжение за пределами рабочего диапазона модуля слишком долго.
  return this->tds_out_of_range_since_ != 0 && now - this->tds_out_of_range_since_ >= this->tds_fault_delay_ms_;
}

Health SmartOsmos::health() const {
  if (this->tds_fault())
    return HEALTH_TDS_FAULT;
  bool low = false;
  for (uint8_t i = 0; i < OSMOS_STAGES; i++) {
    const StageLevel level = this->stage_level(i);
    if (level == STAGE_LEVEL_CRITICAL || level == STAGE_LEVEL_DEAD)
      return HEALTH_BAD;
    if (level == STAGE_LEVEL_LOW)
      low = true;
  }
  if (this->tds_ > this->tds_high_ppm_)
    return HEALTH_BAD;
  return low ? HEALTH_LOW : HEALTH_OK;
}

float SmartOsmos::purification_ratio() const {
  if (this->prefs_.total_in <= 0)
    return 0.0f;
  return this->prefs_.total_out * 100.0f / this->prefs_.total_in;
}

float SmartOsmos::efficiency() const {
  const float in = this->minute_in();
  const float out = this->minute_out();
  if (in <= 0 || out <= 0)
    return 0.0f;
  const float pr = 100.0f - (out * 100.0f / in);
  return pr < 0 ? 0.0f : pr;
}

// ---------------------------------------------------------------------------
// Калибровка и коэффициенты
// ---------------------------------------------------------------------------
void SmartOsmos::set_coeff_in(float v) {
  if (!(v > 0) || this->prefs_.coeff_in == v)
    return;
  this->prefs_.coeff_in = v;
  this->save();
}

void SmartOsmos::set_coeff_out(float v) {
  if (!(v > 0) || this->prefs_.coeff_out == v)
    return;
  this->prefs_.coeff_out = v;
  this->save();
}

void SmartOsmos::set_tds_factor(float v) {
  if (!(v > 0) || this->prefs_.tds_factor == v)
    return;
  this->prefs_.tds_factor = v;
  this->save();
}

void SmartOsmos::set_tds_offset(float v) {
  if (this->prefs_.tds_offset == v)
    return;
  this->prefs_.tds_offset = v;
  this->save();
}

void SmartOsmos::set_display_timeout_min(uint16_t v) {
  if (this->prefs_.display_timeout_min == v)
    return;
  this->prefs_.display_timeout_min = v;
  this->save();
}

void SmartOsmos::calibration_start() {
  this->calib_pulses_ = 0;
  this->calib_active_ = true;
  ESP_LOGI(TAG, "Калибровка чистой линии запущена — пропустите ровно 1 л");
}

void SmartOsmos::calibration_finish(float liters) {
  if (!this->calib_active_)
    return;
  this->calib_active_ = false;
  if (this->calib_pulses_ < 10 || !(liters > 0)) {
    ESP_LOGW(TAG, "Калибровка отменена: импульсов слишком мало (%u)", this->calib_pulses_);
    return;
  }
  const float ppl = this->calib_pulses_ / liters;
  ESP_LOGI(TAG, "Калибровка завершена: %u импульсов на %.2f л = %.1f имп/л", this->calib_pulses_, liters, ppl);
  this->prefs_.coeff_out = ppl;
  this->save();
}

void SmartOsmos::calibration_cancel() {
  this->calib_active_ = false;
  this->calib_pulses_ = 0;
}

// ---------------------------------------------------------------------------
// Время
// ---------------------------------------------------------------------------
void SmartOsmos::set_epoch(uint32_t epoch) {
  if (epoch < 1600000000UL)  // явно неправдоподобное значение
    return;
  const bool was_valid = this->time_valid();
  this->epoch_base_ = epoch;
  this->epoch_millis_ = millis();
  if (!was_valid) {
    ESP_LOGI(TAG, "Время синхронизировано: %u", epoch);
    // Проставим дату замены тем ступеням, которые сбрасывали без часов.
    for (uint8_t i = 0; i < OSMOS_STAGES; i++) {
      if (this->prefs_.stage_date[i] == 0 && this->prefs_.stage_used[i] == 0)
        this->prefs_.stage_date[i] = epoch;
    }
    this->save();
  }
}

void SmartOsmos::set_tz_offset_min(int16_t minutes) {
  if (this->prefs_.tz_offset_min == minutes)
    return;
  this->prefs_.tz_offset_min = minutes;
  this->save();
}

uint32_t SmartOsmos::now_epoch() const {
  if (this->epoch_base_ == 0)
    return 0;
  return this->epoch_base_ + (millis() - this->epoch_millis_) / 1000;
}

std::string SmartOsmos::format_date(uint32_t epoch) const {
  if (epoch == 0)
    return std::string("--.--.--");
  const time_t t = static_cast<time_t>(epoch) + this->prefs_.tz_offset_min * 60;
  struct tm tmv;
  gmtime_r(&t, &tmv);
  char buf[16];
  snprintf(buf, sizeof(buf), "%02d.%02d.%02d", tmv.tm_mday, tmv.tm_mon + 1, (tmv.tm_year + 1900) % 100);
  return std::string(buf);
}

std::string SmartOsmos::uptime_str() const {
  const uint32_t secs = millis() / 1000;
  char buf[24];
  snprintf(buf, sizeof(buf), "%u:%02u:%02u:%02u", secs / 86400, (secs % 86400) / 3600, (secs % 3600) / 60, secs % 60);
  return std::string(buf);
}

void SmartOsmos::save() {
  if (this->ring_.ready()) {
    if (!this->ring_.append(&this->prefs_))
      ESP_LOGE(TAG, "Не удалось записать состояние в журнал");
  } else {
    this->pref_.save(&this->prefs_);
  }
  this->remember_saved_volume_();
  this->saved_tds_count_ = this->prefs_.tds_day_count;
  this->last_stats_save_ = millis();
}

// ---------------------------------------------------------------------------
// BLE-протокол, совместимый с приложением smart_osmos
// ---------------------------------------------------------------------------
std::string SmartOsmos::realtime_json() {
  std::string j;
  j.reserve(448);
  j += '{';
  json_kv_str(j, "key", "real_time", true);
  json_kv_str(j, "r_cur_in", fmt("%.2f", this->prefs_.total_in));
  json_kv_str(j, "r_cur_out", fmt("%.2f", this->prefs_.total_out));
  // Плата ESP32-H2 не имеет Wi-Fi. Поля оставлены ради совместимости с приложением.
  json_kv_str(j, "wi-fi_s", "");
  json_kv_str(j, "wi-fi_st", "disconnect");
  json_kv_raw(j, "wi-fi_rssi", "0");
  json_kv_str(j, "tds", fmt("%.2f", this->tds_));
  json_kv_str(j, "prs", "0.00");
  json_kv_str(j, "mqttstat", "disconnect");
  json_kv_str(j, "lp5mIn", fmt("%.2f", this->minute_in()));
  json_kv_str(j, "lp5mOut", fmt("%.2f", this->minute_out()));
  json_kv_str(j, "effic", fmt("%.2f", this->efficiency()));
  json_kv_str(j, "timework", this->uptime_str());
  // Приложение знает три ступени: предфильтры, мембрана, постфильтр.
  // Из пяти наших ступеней 1..3 — предфильтры, 4 — мембрана, 5 — постфильтр.
  int pre = 0;
  for (uint8_t i = 0; i < 3; i++)
    pre = std::max(pre, this->stage_used_pct(i));
  json_kv_raw(j, "res_P", itos(pre));
  json_kv_raw(j, "res_M", itos(this->stage_used_pct(3)));
  json_kv_raw(j, "res_PO", itos(this->stage_used_pct(4)));
  json_kv_str(j, "ip", "0.0.0.0");
  json_kv_str(j, "flow_in", fmt("%.2f", this->flow_in_));
  json_kv_str(j, "flow_out", fmt("%.2f", this->flow_out_));
  json_kv_raw(j, "ota_en", this->ota_enabled_ ? "true" : "false");
  json_kv_str(j, "ota_link", "ble");
  j += '}';
  return j;
}

std::string SmartOsmos::config_json() {
  std::string j;
  j.reserve(256);
  j += '{';
  json_kv_str(j, "key", "config_data", true);
  json_kv_raw(j, "co_c_in", itos(lroundf(this->prefs_.coeff_in)));
  json_kv_raw(j, "co_c_out", itos(lroundf(this->prefs_.coeff_out)));
  json_kv_raw(j, "prefiltr", itos(this->prefs_.stage_limit[0]));
  json_kv_raw(j, "membrana", itos(this->prefs_.stage_limit[3]));
  json_kv_raw(j, "postfiltr", itos(this->prefs_.stage_limit[4]));
  json_kv_str(j, "ssid", "");
  json_kv_str(j, "mqtt_serv", "");
  json_kv_str(j, "mqtt_user", "");
  json_kv_str(j, "mqtt_topic", "");
  j += '}';
  return j;
}

std::string SmartOsmos::ext_json() {
  std::string j;
  j.reserve(384);
  j += '{';
  json_kv_str(j, "key", "ext", true);
  json_kv_raw(j, "tds", fmt("%.1f", this->tds_));
  json_kv_raw(j, "tds_v", fmt("%.4f", this->tds_voltage_));
  json_kv_raw(j, "tds_min", fmt("%.1f", std::isnan(this->tds_day_min()) ? 0.0f : this->tds_day_min()));
  json_kv_raw(j, "tds_avg", fmt("%.1f", std::isnan(this->tds_day_avg()) ? 0.0f : this->tds_day_avg()));
  json_kv_raw(j, "tds_max", fmt("%.1f", std::isnan(this->tds_day_max()) ? 0.0f : this->tds_day_max()));
  json_kv_raw(j, "f_in", fmt("%.2f", this->flow_in_));
  json_kv_raw(j, "f_out", fmt("%.2f", this->flow_out_));
  json_kv_raw(j, "m_in", fmt("%.3f", this->minute_in()));
  json_kv_raw(j, "m_out", fmt("%.3f", this->minute_out()));
  json_kv_raw(j, "t_in", fmt("%.2f", this->prefs_.total_in));
  json_kv_raw(j, "t_out", fmt("%.2f", this->prefs_.total_out));
  json_kv_raw(j, "purif", fmt("%.1f", this->purification_ratio()));
  json_kv_raw(j, "effic", fmt("%.1f", this->efficiency()));
  json_kv_raw(j, "cal", this->calib_active_ ? "1" : "0");
  json_kv_raw(j, "cal_p", itos(this->calib_pulses_));
  json_kv_raw(j, "ts", itos(this->now_epoch()));
  json_kv_raw(j, "tdsf", this->tds_fault() ? "1" : "0");
  json_kv_raw(j, "hl", itos(this->health()));

  std::string rem = "[", used = "[";
  for (uint8_t i = 0; i < OSMOS_STAGES; i++) {
    if (i) {
      rem += ',';
      used += ',';
    }
    rem += fmt("%.1f", this->stage_remaining(i));
    used += fmt("%.1f", this->prefs_.stage_used[i]);
  }
  rem += ']';
  used += ']';
  json_kv_raw(j, "r", rem);
  json_kv_raw(j, "u", used);
  j += '}';
  return j;
}

std::string SmartOsmos::ext_config_json() {
  std::string j;
  j.reserve(320);
  j += '{';
  json_kv_str(j, "key", "ext_config", true);
  json_kv_raw(j, "c_in", fmt("%.1f", this->prefs_.coeff_in));
  json_kv_raw(j, "c_out", fmt("%.1f", this->prefs_.coeff_out));
  json_kv_raw(j, "tds_factor", fmt("%.4f", this->prefs_.tds_factor));
  json_kv_raw(j, "tds_offset", fmt("%.2f", this->prefs_.tds_offset));
  json_kv_raw(j, "tz", itos(this->prefs_.tz_offset_min));
  json_kv_raw(j, "dt", itos(this->prefs_.display_timeout_min));
  json_kv_str(j, "fw", this->firmware_version_);
  json_kv_raw(j, "st", this->ring_.ready() ? "1" : "0");

  std::string lim = "[", date = "[", src = "[";
  for (uint8_t i = 0; i < OSMOS_STAGES; i++) {
    if (i) {
      lim += ',';
      date += ',';
      src += ',';
    }
    lim += itos(this->prefs_.stage_limit[i]);
    date += itos(this->prefs_.stage_date[i]);
    src += itos(this->prefs_.stage_source[i]);
  }
  lim += ']';
  date += ']';
  src += ']';
  json_kv_raw(j, "limit", lim);
  json_kv_raw(j, "date", date);
  json_kv_raw(j, "src", src);
  j += '}';
  return j;
}

bool SmartOsmos::take_config_request() {
  const bool r = this->config_requested_;
  this->config_requested_ = false;
  return r;
}

void SmartOsmos::handle_command(const std::string &payload) {
  if (payload.size() < 2)
    return;
  std::string key;
  if (!json_field(payload, "key", key)) {
    ESP_LOGW(TAG, "Команда без ключа: %s", payload.c_str());
    return;
  }
  ESP_LOGD(TAG, "Команда BLE: %s", key.c_str());

  if (key == "get_config") {
    this->stream_enabled_ = false;
    this->config_requested_ = true;

  } else if (key == "get_data") {
    std::string en;
    this->stream_enabled_ = json_field(payload, "en", en) && en == "On";

  } else if (key == "c_config") {
    uint32_t v;
    if (json_field_u32(payload, "c_in", v) && v > 0)
      this->prefs_.coeff_in = static_cast<float>(v);
    if (json_field_u32(payload, "c_off", v) && v > 0)
      this->prefs_.coeff_out = static_cast<float>(v);
    if (json_field_u32(payload, "prefiltr", v)) {
      // Приложение задаёт один ресурс на все предфильтры.
      for (uint8_t i = 0; i < 3; i++)
        this->prefs_.stage_limit[i] = v;
    }
    if (json_field_u32(payload, "membrana", v))
      this->prefs_.stage_limit[3] = v;
    if (json_field_u32(payload, "postfiltr", v))
      this->prefs_.stage_limit[4] = v;
    this->save();

  } else if (key == "c_reset") {
    std::string v;
    if (json_field(payload, "r_totalIN_P", v) && v == "R") {
      for (uint8_t i = 0; i < 3; i++)
        this->reset_stage(i);
    }
    if (json_field(payload, "r_totalIN_M", v) && v == "R")
      this->reset_stage(3);
    if (json_field(payload, "r_totalIN_PO", v) && v == "R")
      this->reset_stage(4);
    if (json_field(payload, "r_totalIN_OUT", v) && v == "R")
      this->reset_totals();

  } else if (key == "update") {
    std::string en, psw;
    json_field(payload, "en", en);
    json_field(payload, "psw", psw);
    while (!psw.empty() && std::isspace(static_cast<unsigned char>(psw.back())))
      psw.pop_back();
    this->ota_enabled_ = (en == "On" && psw == this->ota_password_);
    ESP_LOGI(TAG, "Обновление по BLE %s", this->ota_enabled_ ? "разрешено" : "запрещено");

  } else if (key == "time") {
    // Расширение протокола: синхронизация часов от приложения или Home Assistant.
    uint32_t ts;
    if (json_field_u32(payload, "ts", ts))
      this->set_epoch(ts);
    float tz;
    if (json_field_float(payload, "tz", tz))
      this->set_tz_offset_min(static_cast<int16_t>(lroundf(tz)));

  } else if (key == "stage") {
    // Расширение протокола: работа со всеми пятью ступенями.
    uint32_t idx;
    if (!json_field_u32(payload, "n", idx) || idx < 1 || idx > OSMOS_STAGES)
      return;
    const uint8_t i = static_cast<uint8_t>(idx - 1);
    uint32_t limit;
    if (json_field_u32(payload, "limit", limit))
      this->set_stage_limit(i, limit);
    uint32_t src;
    if (json_field_u32(payload, "src", src))
      this->set_stage_source(i, src ? STAGE_SRC_PERMEATE : STAGE_SRC_INLET);
    std::string reset;
    if (json_field(payload, "reset", reset) && reset == "R")
      this->reset_stage(i);

  } else if (key == "cal") {
    std::string act;
    if (!json_field(payload, "act", act))
      return;
    if (act == "start") {
      this->calibration_start();
    } else if (act == "finish") {
      float liters = 1.0f;
      json_field_float(payload, "l", liters);
      this->calibration_finish(liters);
    } else if (act == "cancel") {
      this->calibration_cancel();
    }

  } else if (key == "tds_cal") {
    float v;
    if (json_field_float(payload, "factor", v))
      this->set_tds_factor(v);
    if (json_field_float(payload, "offset", v))
      this->set_tds_offset(v);
    std::string act;
    if (json_field(payload, "act", act) && act == "day_reset")
      this->reset_day_stats();

  } else if (key == "display") {
    // Расширение протокола: таймаут гашения дисплея, минут.
    uint32_t minutes;
    if (json_field_u32(payload, "timeout", minutes) && minutes >= 1 && minutes <= 1440)
      this->set_display_timeout_min(static_cast<uint16_t>(minutes));

  } else if (key == "wifi" || key == "wifien" || key == "save") {
    // Wi-Fi на ESP32-H2 нет. Команды принимаются и игнорируются, чтобы
    // приложение не считало устройство неответившим.
    ESP_LOGD(TAG, "Команда «%s» пропущена: у платы нет Wi-Fi", key.c_str());
  }
}

// ---------------------------------------------------------------------------
// Отрисовка шкал ресурса
// ---------------------------------------------------------------------------
#ifdef USE_DISPLAY
bool stage_visible(StageLevel level, uint32_t now_ms) {
  switch (level) {
    case STAGE_LEVEL_LOW:
      return ((now_ms / 2000) % 2) == 0;  // 0.25 Гц
    case STAGE_LEVEL_CRITICAL:
      return ((now_ms / 1000) % 2) == 0;  // 0.5 Гц
    default:
      return true;
  }
}

bool draw_stage_bar(display::Display *it, int x, int y, int w, int h, float remaining_pct, StageLevel level,
                    uint32_t now_ms) {
  if (!stage_visible(level, now_ms))
    return false;

  it->rectangle(x, y, w, h);
  switch (level) {
    case STAGE_LEVEL_DEAD:
      // Ресурс исчерпан: две пересекающиеся линии.
      it->line(x, y, x + w - 1, y + h - 1);
      it->line(x + w - 1, y, x, y + h - 1);
      break;
    case STAGE_LEVEL_CRITICAL:
      // Менее 5 %: шкала пустая, перечёркнута одной наклонной линией.
      it->line(x, y + h - 1, x + w - 1, y);
      break;
    default: {
      const int inner = w - 2;
      const int fill = static_cast<int>(lroundf(inner * clamp(remaining_pct, 0.0f, 100.0f) / 100.0f));
      if (fill > 0)
        it->filled_rectangle(x + 1, y + 1, fill, h - 2);
      break;
    }
  }
  return true;
}
#endif

}  // namespace smart_osmos
}  // namespace esphome
