#include "flash_ring.h"

#include <cstring>
#include <vector>

namespace esphome {
namespace smart_osmos {

uint32_t crc32_update(uint32_t crc, const uint8_t *data, size_t len) {
  crc = ~crc;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int k = 0; k < 8; k++)
      crc = (crc & 1) ? (crc >> 1) ^ 0xEDB88320u : crc >> 1;
  }
  return ~crc;
}

uint32_t FlashRing::crc_of_(uint32_t seq, const uint8_t *data, size_t len) const {
  // Номер записи входит в CRC: так данные из чужого слота не сойдут за свои.
  uint8_t seq_bytes[4] = {uint8_t(seq), uint8_t(seq >> 8), uint8_t(seq >> 16), uint8_t(seq >> 24)};
  return crc32_update(crc32_update(0, seq_bytes, 4), data, len);
}

bool FlashRing::begin(FlashIO *io, size_t payload_size) {
  this->io_ = nullptr;
  if (io == nullptr || payload_size == 0 || payload_size > 0xFFFF)
    return false;

  size_t slot = 32;
  while (slot < HEADER_SIZE + payload_size)
    slot <<= 1;
  if (slot > io->sector_size() || io->size() < 2 * io->sector_size())
    return false;  // нужно минимум два сектора: один всегда хранит последнюю запись

  this->io_ = io;
  this->payload_size_ = payload_size;
  this->slot_size_ = slot;
  this->slot_count_ = (io->size() / io->sector_size()) * (io->sector_size() / slot);
  this->latest_ = -1;
  this->seq_ = 0;
  this->erases_ = 0;

  // Ищем целую запись с наибольшим номером.
  for (size_t i = 0; i < this->slot_count_; i++) {
    Header h;
    if (this->slot_valid_(i, &h) && (this->latest_ < 0 || h.seq > this->seq_)) {
      this->latest_ = static_cast<int32_t>(i);
      this->seq_ = h.seq;
    }
  }
  this->next_ = this->latest_ < 0 ? 0 : (static_cast<size_t>(this->latest_) + 1) % this->slot_count_;
  return true;
}

bool FlashRing::slot_empty_(size_t slot) const {
  uint8_t buf[HEADER_SIZE];
  if (!this->io_->read(this->offset_of_(slot), buf, sizeof(buf)))
    return false;
  for (uint8_t b : buf) {
    if (b != 0xFF)
      return false;
  }
  return true;
}

bool FlashRing::slot_valid_(size_t slot, Header *out) const {
  Header h;
  if (!this->io_->read(this->offset_of_(slot), &h, sizeof(h)))
    return false;
  if (h.magic != COMMIT_MAGIC || h.length != this->payload_size_)
    return false;
  std::vector<uint8_t> data(this->payload_size_);
  if (!this->io_->read(this->offset_of_(slot) + HEADER_SIZE, data.data(), data.size()))
    return false;
  if (this->crc_of_(h.seq, data.data(), data.size()) != h.crc)
    return false;
  if (out != nullptr)
    *out = h;
  return true;
}

bool FlashRing::load(void *dst) const {
  if (this->io_ == nullptr || this->latest_ < 0)
    return false;
  return this->io_->read(this->offset_of_(this->latest_) + HEADER_SIZE, dst, this->payload_size_);
}

bool FlashRing::append(const void *src) {
  if (this->io_ == nullptr)
    return false;
  const auto *data = static_cast<const uint8_t *>(src);
  const uint32_t seq = this->seq_ + 1;

  // Обычно хватает первой же попытки. Повторы нужны, если слот оказался
  // испорчен (оборванная запись) или запись не прошла проверку чтением.
  for (size_t attempt = 0; attempt < this->slot_count_; attempt++) {
    const size_t slot = this->next_;
    this->next_ = (slot + 1) % this->slot_count_;

    if (this->sector_start_(slot)) {
      // Сектор с последней целой записью не стираем никогда: иначе обрыв
      // питания в этот момент оставил бы журнал пустым.
      const size_t sector = this->io_->sector_size();
      if (this->latest_ >= 0 && this->offset_of_(this->latest_) / sector == this->offset_of_(slot) / sector)
        continue;
      // Новый сектор хранит самые старые записи — их и стираем.
      if (!this->io_->erase_sector(this->offset_of_(slot)))
        continue;
      this->erases_++;
    } else if (!this->slot_empty_(slot)) {
      continue;
    }

    Header h;
    h.magic = 0xFFFFFFFF;  // маркер ставится последним
    h.seq = seq;
    h.length = static_cast<uint16_t>(this->payload_size_);
    h.reserved = 0xFFFF;
    h.crc = this->crc_of_(seq, data, this->payload_size_);

    const size_t base = this->offset_of_(slot);
    if (!this->io_->write(base + HEADER_SIZE, data, this->payload_size_))
      continue;
    if (!this->io_->write(base + 4, &h.seq, HEADER_SIZE - 4))
      continue;
    const uint32_t magic = COMMIT_MAGIC;
    if (!this->io_->write(base, &magic, sizeof(magic)))
      continue;

    if (!this->slot_valid_(slot, nullptr))
      continue;  // не прочиталось как записано — пробуем следующий слот

    this->latest_ = static_cast<int32_t>(slot);
    this->seq_ = seq;
    return true;
  }
  return false;
}

}  // namespace smart_osmos
}  // namespace esphome
