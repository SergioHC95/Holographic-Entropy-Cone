// Offline exact audit of 64/128-bit historical numerator tables.
// Build: c++ -O3 -std=c++17 tools/audit_counts.cpp -o audit_counts
// No solver, floating point, mmap, table-sized allocation, or wall timeout.
// Config is HECCNT01, all integers unsigned little-endian. Wider historical
// tables require an explicit wider auditor; this program fails closed.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

using Integer = unsigned __int128;
constexpr Integer MAXIMUM = ~Integer(0);

static Integer integer(const unsigned char* p, unsigned bytes) {
  Integer value = 0;
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
  // memcpy is safe for unaligned table rows and folds to one/two word loads
  // in the constant-width audit loops. It does not alias through a cast.
  std::memcpy(&value, p, bytes);
#else
  for (unsigned i = 0; i < bytes; ++i) value |= Integer(p[i]) << (8 * i);
#endif
  return value;
}
static uint64_t read_number(std::ifstream& source, unsigned bytes) {
  unsigned char value[8]{};
  if (bytes > 8 || !source.read(reinterpret_cast<char*>(value), bytes))
    throw std::runtime_error("truncated audit configuration");
  return uint64_t(integer(value, bytes));
}
static Integer product(Integer value, uint64_t multiplier) {
  if (multiplier && value > MAXIMUM / multiplier)
    throw std::runtime_error("128-bit audit configuration overflow");
  return value * multiplier;
}
static void read_at(int fd, unsigned char* output, size_t bytes, uint64_t offset) {
  while (bytes) {
    ssize_t size = pread(fd, output, bytes, static_cast<off_t>(offset));
    if (size <= 0) throw std::runtime_error("truncated numerator table");
    output += size; bytes -= size; offset += size;
  }
}
static std::string decimal(Integer value) {
  if (!value) return "0";
  std::string output;
  while (value) { output.push_back('0' + value % 10); value /= 10; }
  std::reverse(output.begin(), output.end());
  return output;
}

template<unsigned WIDTH>
static void audit(int fd, unsigned L, unsigned G, uint64_t N,
                  const std::vector<Integer>& limits, const std::vector<Integer>& capacities) {
  constexpr uint64_t BATCH = 4096;
  const uint64_t row_bytes = G * WIDTH;
  std::vector<unsigned char> a(BATCH * row_bytes), b(BATCH * row_bytes);
  for (uint64_t first = 0; first < N; first += BATCH) {
    uint64_t count = std::min(BATCH, N - first);
    read_at(fd, a.data(), count * row_bytes, first * row_bytes);
    for (uint64_t row = 0; row < count; ++row)
      for (unsigned group = 0; group < G; ++group)
        if (integer(a.data() + row * row_bytes + group * WIDTH, WIDTH) > limits[group])
          throw std::runtime_error("numerator outside RHS count bound");
  }
  std::vector<Integer> maximum(L);
  uint64_t checked = 0;
  for (unsigned axis = 0; axis < L; ++axis) {
    uint64_t side = uint64_t(1) << axis;
    // Each (axis, block, offset) names one unique original cube edge.
    // Small axes read a contiguous batch once; larger axes read its two sides.
    if (side < BATCH) {
      for (uint64_t first = 0; first < N; first += BATCH) {
        uint64_t count = std::min(BATCH, N - first);
        read_at(fd, a.data(), count * row_bytes, first * row_bytes);
        for (uint64_t row = 0; row < count; ++row) if (!(row & side)) {
          Integer distance = 0;
          for (unsigned group = 0; group < G; ++group) {
            Integer x = integer(a.data() + row * row_bytes + group * WIDTH, WIDTH);
            Integer y = integer(a.data() + (row + side) * row_bytes + group * WIDTH, WIDTH);
            distance += x >= y ? x - y : y - x;
          }
          if (distance > capacities[axis]) throw std::runtime_error("original cube edge violation");
          maximum[axis] = std::max(maximum[axis], distance); ++checked;
        }
      }
    } else {
      for (uint64_t block = 0; block < N; block += 2 * side)
        for (uint64_t first = 0; first < side; first += BATCH) {
          uint64_t count = std::min(BATCH, side - first);
          read_at(fd, a.data(), count * row_bytes, (block + first) * row_bytes);
          read_at(fd, b.data(), count * row_bytes, (block + side + first) * row_bytes);
          for (uint64_t row = 0; row < count; ++row) {
            Integer distance = 0;
            for (unsigned group = 0; group < G; ++group) {
              Integer x = integer(a.data() + row * row_bytes + group * WIDTH, WIDTH);
              Integer y = integer(b.data() + row * row_bytes + group * WIDTH, WIDTH);
              distance += x >= y ? x - y : y - x;
            }
            if (distance > capacities[axis]) throw std::runtime_error("original cube edge violation");
            maximum[axis] = std::max(maximum[axis], distance); ++checked;
          }
        }
    }
  }
  if (checked != L * (N / 2)) throw std::runtime_error("incomplete original cube edge coverage");
  std::cout << "{\"ok\":true,\"checked_edges\":" << checked
            << ",\"axis_maximum_load_numerators\":[";
  for (unsigned i = 0; i < L; ++i) {
    if (i) std::cout << ',';
    std::cout << std::quoted(decimal(maximum[i]));
  }
  std::cout << "]}\n";
}

int main(int argc, char** argv) {
  int fd = -1;
  try {
    if (argc != 4 || std::string(argv[3]) != "1")
      throw std::runtime_error("usage: audit_counts config.bin counts.raw 1");
    std::ifstream config(argv[1], std::ios::binary);
    char magic[8];
    if (!config.read(magic, 8) || std::string(magic, 8) != "HECCNT01")
      throw std::runtime_error("invalid audit configuration magic");
    unsigned L = read_number(config, 4), G = read_number(config, 4);
    unsigned width = read_number(config, 4), atoms = read_number(config, 4);
    uint64_t N = read_number(config, 8);
    if (L < 1 || L > 30 || G < 1 || G > 63 || (width != 8 && width != 16)
        || atoms < 1 || atoms > 64 || N != (uint64_t(1) << L))
      throw std::runtime_error("unsupported audit dimensions/width");
    std::vector<uint64_t> alpha(L), beta(G), boundary(atoms);
    for (auto& value : alpha) if (!(value = read_number(config, 8)))
      throw std::runtime_error("nonpositive source capacity");
    for (auto& value : beta) if (!(value = read_number(config, 8)))
      throw std::runtime_error("nonpositive RHS multiplicity");
    unsigned char raw_scale[16]{};
    if (!config.read(reinterpret_cast<char*>(raw_scale), width))
      throw std::runtime_error("truncated audit scale");
    Integer scale = integer(raw_scale, width);
    if (!scale) throw std::runtime_error("nonpositive clearing scale");
    for (auto& value : boundary) if ((value = read_number(config, 8)) >= N)
      throw std::runtime_error("occurrence boundary outside source cube");
    std::vector<unsigned char> flags(atoms * G);
    if (!config.read(reinterpret_cast<char*>(flags.data()), flags.size()) || config.peek() != EOF)
      throw std::runtime_error("truncated/trailing audit configuration");
    for (auto value : flags) if (value > 1) throw std::runtime_error("nonbinary boundary flag");
    std::vector<Integer> limits(G), capacities(L);
    Integer maximum_distance = 0;
    for (unsigned i = 0; i < G; ++i) {
      limits[i] = product(scale, beta[i]);
      if (maximum_distance > MAXIMUM - limits[i]) throw std::runtime_error("128-bit edge accumulator overflow");
      maximum_distance += limits[i];
    }
    for (unsigned i = 0; i < L; ++i) capacities[i] = product(scale, alpha[i]);
    fd = open(argv[2], O_RDONLY);
    struct stat stat{};
    if (fd < 0 || fstat(fd, &stat) || uint64_t(stat.st_size) != N * G * width)
      throw std::runtime_error("original numerator byte length mismatch");
    std::vector<unsigned char> row(G * width);
    for (unsigned atom = 0; atom < atoms; ++atom) {
      read_at(fd, row.data(), row.size(), boundary[atom] * row.size());
      for (unsigned group = 0; group < G; ++group)
        if (integer(row.data() + group * width, width) != (flags[atom * G + group] ? limits[group] : 0))
          throw std::runtime_error("original occurrence boundary mismatch");
    }
    if (width == 8) audit<8>(fd, L, G, N, limits, capacities);
    else audit<16>(fd, L, G, N, limits, capacities);
    close(fd);
    return 0;
  } catch (const std::exception& error) {
    if (fd >= 0) close(fd);
    std::cout << "{\"ok\":false,\"error\":" << std::quoted(error.what()) << "}\n";
    return 2;
  }
}
