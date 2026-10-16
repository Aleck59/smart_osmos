// Проверка кольцевого журнала на ПК: g++ -std=c++17 -I esphome/components ...
// Эмулирует NOR-flash (запись только сбрасывает биты, стирание — секторами)
// и обрывы питания посреди записи.
#include "smart_osmos/flash_ring.h"

#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

using esphome::smart_osmos::FlashIO;
using esphome::smart_osmos::FlashRing;

struct PowerLoss {};

class RamFlash : public FlashIO {
 public:
  explicit RamFlash(size_t size) : mem(size), erase_count(size / 4096, 0) {
    std::mt19937 rng(7);  // «грязная» область: остатки старой прошивки
    for (auto &b : mem) b = uint8_t(rng());
  }
  size_t size() const override { return mem.size(); }
  bool read(size_t off, void *dst, size_t len) override {
    std::memcpy(dst, &mem[off], len);
    return true;
  }
  bool write(size_t off, const void *src, size_t len) override {
    const auto *s = static_cast<const uint8_t *>(src);
    for (size_t i = 0; i < len; i++) {
      if (budget == 0) throw PowerLoss{};
      if (budget > 0) budget--;
      mem[off + i] &= s[i];  // NOR: единицы в нули, обратно — только стиранием
    }
    return true;
  }
  bool erase_sector(size_t off) override {
    if (budget == 0) throw PowerLoss{};
    std::fill(mem.begin() + off, mem.begin() + off + 4096, 0xFF);
    erase_count[off / 4096]++;
    return true;
  }
  std::vector<uint8_t> mem;
  std::vector<uint32_t> erase_count;
  long budget = -1;  // сколько байт ещё успеет записаться до «отключения питания»
};

struct Record {
  uint32_t liters;
  float payload[30];
};

static Record make(uint32_t n) {
  Record r{};
  r.liters = n;
  for (int i = 0; i < 30; i++) r.payload[i] = float(n) * 0.5f + float(i);
  return r;
}

int main() {
  const size_t AREA = 64 * 1024;

  // 1. Пустая (грязная) область: первая запись и чтение.
  RamFlash flash(AREA);
  FlashRing ring;
  assert(ring.begin(&flash, sizeof(Record)));
  assert(!ring.has_record());
  printf("слот %zu Б, слотов %zu (секторов %zu)\n", ring.slot_size(), ring.slot_count(), AREA / 4096);
  Record r = make(1);
  assert(ring.append(&r));
  Record got{};
  assert(ring.load(&got) && got.liters == 1);

  // 2. Тысячи записей «по литру»: последняя читается, износ равномерный.
  const uint32_t N = 20000;
  for (uint32_t n = 2; n <= N; n++) {
    r = make(n);
    assert(ring.append(&r));
  }
  assert(ring.load(&got) && got.liters == N && std::memcmp(&got, &r, sizeof(r)) == 0);
  auto [mn, mx] = std::minmax_element(flash.erase_count.begin(), flash.erase_count.end());
  printf("%u записей: стираний на сектор от %u до %u (одна ячейка без журнала: %u перезаписей)\n",
         N, *mn, *mx, N);
  assert(*mx - *mn <= 1);

  // 3. Перезагрузка: журнал восстанавливается с того же места.
  FlashRing again;
  assert(again.begin(&flash, sizeof(Record)) && again.load(&got) && got.liters == N);
  assert(again.sequence() == ring.sequence());

  // 4. Обрыв питания в каждой возможной точке записи.
  std::mt19937 rng(42);
  uint32_t current = N, torn = 0, completed = 0;
  for (int trial = 0; trial < 3000; trial++) {
    FlashRing live;
    assert(live.begin(&flash, sizeof(Record)) && live.load(&got) && got.liters == current);
    r = make(current + 1);
    flash.budget = long(rng() % (sizeof(Record) + 40));
    try {
      live.append(&r);
      completed++;
      current++;
    } catch (PowerLoss &) {
      torn++;
    }
    flash.budget = -1;
    FlashRing after;
    assert(after.begin(&flash, sizeof(Record)) && after.load(&got));
    // После сбоя читается либо старая запись целиком, либо новая целиком.
    assert(got.liters == current || got.liters == current + 1);
    if (got.liters == current + 1) current++;
    Record expect = make(got.liters);
    assert(std::memcmp(&got, &expect, sizeof(expect)) == 0);
  }
  printf("3000 обрывов питания (%u посреди записи, %u успели): журнал ни разу не потерял данные\n",
         torn, completed);

  // 5. После сбоев журнал продолжает работать.
  FlashRing tail;
  assert(tail.begin(&flash, sizeof(Record)));
  for (int i = 0; i < 500; i++) {
    r = make(++current);
    assert(tail.append(&r));
  }
  assert(tail.load(&got) && got.liters == current);
  puts("ВСЕ ПРОВЕРКИ ЖУРНАЛА ПРОЙДЕНЫ");
  return 0;
}
