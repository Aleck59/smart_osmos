#pragma once

#include <cstddef>
#include <cstdint>

namespace esphome {
namespace smart_osmos {

/// Доступ к области flash: чтение, запись и стирание сектора.
/// Отдельный интерфейс нужен, чтобы журнал можно было проверить на ПК без железа.
class FlashIO {
 public:
  virtual ~FlashIO() = default;
  virtual size_t size() const = 0;
  virtual size_t sector_size() const { return 4096; }
  virtual bool read(size_t offset, void *dst, size_t len) = 0;
  virtual bool write(size_t offset, const void *src, size_t len) = 0;
  virtual bool erase_sector(size_t offset) = 0;
};

/// Кольцевой журнал записей фиксированного размера с распределением износа.
///
/// Вместо перезаписи одной ячейки каждое сохранение кладётся в следующий слот
/// области; при переходе на новый сектор он стирается целиком. Так износ
/// равномерно распределяется по всей области — по тому же принципу, по которому
/// работает эмуляция EEPROM.
///
/// Слот: заголовок 16 байт + данные, размер округлён до степени двойки, чтобы
/// слоты не пересекали границы секторов. Запись фиксируется маркером, который
/// пишется последним, а данные защищены CRC-32. Поэтому оборванная при
/// пропадании питания запись не портит журнал: при загрузке берётся последняя
/// целая запись с наибольшим порядковым номером.
class FlashRing {
 public:
  /// Подготовить журнал. Возвращает false, если область слишком мала.
  bool begin(FlashIO *io, size_t payload_size);
  /// Прочитать последнюю целую запись. false — записей нет.
  bool load(void *dst) const;
  /// Дописать новую запись.
  bool append(const void *src);

  bool ready() const { return this->io_ != nullptr; }
  bool has_record() const { return this->latest_ >= 0; }
  uint32_t sequence() const { return this->seq_; }
  size_t slot_size() const { return this->slot_size_; }
  size_t slot_count() const { return this->slot_count_; }
  /// Сколько раз стирались сектора с момента begin() — для журнала и тестов.
  uint32_t erases() const { return this->erases_; }

  static const uint32_t COMMIT_MAGIC = 0x52534F4D;  // "MOSR"
  static const size_t HEADER_SIZE = 16;

 protected:
  struct Header {
    uint32_t magic;
    uint32_t seq;
    uint16_t length;
    uint16_t reserved;
    uint32_t crc;
  };

  size_t offset_of_(size_t slot) const { return slot * this->slot_size_; }
  bool sector_start_(size_t slot) const { return this->offset_of_(slot) % this->io_->sector_size() == 0; }
  bool slot_empty_(size_t slot) const;
  bool slot_valid_(size_t slot, Header *out) const;
  uint32_t crc_of_(uint32_t seq, const uint8_t *data, size_t len) const;

  FlashIO *io_{nullptr};
  size_t payload_size_{0};
  size_t slot_size_{0};
  size_t slot_count_{0};
  int32_t latest_{-1};
  size_t next_{0};
  uint32_t seq_{0};
  uint32_t erases_{0};
};

uint32_t crc32_update(uint32_t crc, const uint8_t *data, size_t len);

}  // namespace smart_osmos
}  // namespace esphome
