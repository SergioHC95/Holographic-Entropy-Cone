// Offline independent full-cube audit: uint64 exact numerators, uint128 sums.
// The earlier narrow verifier and recipe versions are deliberately unchanged.
// Mode 0 accepts reconstructed C counts, never receipts or source tables.
// Mode 1 audits an original packed Boolean map and extracts its complete C.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <functional>
#include <iostream>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using Wide = unsigned __int128;
static void need(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
static uint64_t get(unsigned bytes) {
  unsigned char data[8]{};
  need(bytes <= 8 && bool(std::cin.read(reinterpret_cast<char*>(data), bytes)), "truncated request");
  uint64_t result = 0;
  for (unsigned i = 0; i < bytes; ++i) result |= uint64_t(data[i]) << (8 * i);
  return result;
}
static void put(uint64_t value, unsigned bytes) {
  for (unsigned i = 0; i < bytes; ++i) std::cout.put(char(value >> (8 * i)));
}
struct Pair { unsigned i, j; };
struct Problem {
  unsigned n, L, G, R;
  uint32_t N;
  uint64_t normalizer = 1;
  std::vector<unsigned> lhs, alpha, rhs, beta;
  std::vector<Pair> disjoint, nested;
  std::vector<uint32_t> vertices, boundary;
  std::vector<int32_t> index;
  Problem(unsigned parties, const std::vector<int32_t>& coefficients) : n(parties) {
    need(n >= 1 && n <= 6 && coefficients.size() == (1u << n) - 1, "unsupported party dimension");
    std::vector<unsigned> supports;
    for (unsigned size = 1; size <= n; ++size) {
      std::function<void(unsigned, unsigned, unsigned)> visit = [&](unsigned first, unsigned left, unsigned mask) {
        if (!left) { supports.push_back(mask); return; }
        for (unsigned i = first; i + left <= n; ++i) visit(i + 1, left - 1, mask | (1u << i));
      };
      visit(0, size, 0);
    }
    unsigned divisor = 0;
    for (unsigned i = 0; i < coefficients.size(); ++i) {
      int64_t v = coefficients[i];
      need(v >= -1024 && v <= 1024, "capacity beyond bounded wide checker");
      divisor = std::gcd(divisor, unsigned(v < 0 ? -v : v));
      if (v > 0) { lhs.push_back(supports[i]); alpha.push_back(unsigned(v)); }
      if (v < 0) { rhs.push_back(supports[i]); beta.push_back(unsigned(-v)); }
    }
    need(divisor <= 1, "nonprimitive coefficient vector");
    L = lhs.size(); G = rhs.size(); R = std::accumulate(beta.begin(), beta.end(), 0u);
    need(L <= 25 && G <= 63, "geometry needs a larger independent auditor");
    N = 1u << L;
    // Bound actual table allocation, in addition to the external live RSS guard.
    need(Wide(N) * G * 8 + Wide(N) * 4 <= Wide(30) * 1024 * 1024 * 1024, "table allocation exceeds worker allowance");
    for (unsigned a : alpha) {
      Wide v = Wide(normalizer / std::gcd(normalizer, uint64_t(a))) * a;
      need(v <= UINT64_MAX, "threshold normalizer overflow"); normalizer = uint64_t(v);
    }
    std::vector<uint32_t> predecessors(L), conflicts(L);
    for (unsigned i = 0; i < L; ++i) for (unsigned j = 0; j < L; ++j) {
      if (i < j && !(lhs[i] & lhs[j])) {
        disjoint.push_back({i, j}); conflicts[i] |= 1u << j; conflicts[j] |= 1u << i;
      }
      if (i != j && (lhs[i] & lhs[j]) == lhs[i]) {
        need(i < j, "source supports are not subset-first");
        nested.push_back({i, j}); predecessors[j] |= 1u << i;
      }
    }
    std::function<void(int, uint32_t, uint32_t)> domain = [&](int axis, uint32_t zeros, uint32_t value) {
      if (axis < 0) { vertices.push_back(value); return; }
      uint32_t lower = (1u << axis) - 1;
      domain(axis - 1, (zeros | predecessors[axis]) & lower, value);
      if (!(zeros & (1u << axis))) domain(axis - 1, (zeros | conflicts[axis]) & lower, value | (1u << axis));
    };
    domain(int(L) - 1, 0, 0);
    index.assign(N, -1);
    for (unsigned i = 0; i < vertices.size(); ++i) index[vertices[i]] = int32_t(i);
    // Independent exhaustive clause check: recursive generation alone is not trusted.
    uint64_t complete = 0;
    for (uint32_t x = 0; x < N; ++x) {
      bool valid = true;
      for (auto r : disjoint) if ((x & (1u << r.i)) && (x & (1u << r.j))) { valid = false; break; }
      if (valid) for (auto r : nested) if ((x & (1u << r.i)) && !(x & (1u << r.j))) { valid = false; break; }
      need(valid == (index[x] >= 0), "complete compatible domain mismatch"); complete += valid;
    }
    need(complete == vertices.size(), "incomplete compatible enumeration");
    for (unsigned atom = 0; atom <= n; ++atom) {
      uint32_t x = 0;
      for (unsigned i = 0; i < L; ++i) if (lhs[i] & (1u << atom)) x |= 1u << i;
      need(index[x] >= 0, "occurrence outside compatible domain"); boundary.push_back(x);
    }
  }
};
static uint64_t scale_for(const Problem& p, uint64_t seed_scale) {
  need(seed_scale > 0, "zero seed clearing scale");
  bool uniform = p.alpha.empty() || std::all_of(p.alpha.begin(), p.alpha.end(), [&](unsigned a) { return a == p.alpha[0]; });
  Wide scale = Wide(seed_scale) * (uniform ? 1 : p.normalizer);
  need(scale <= UINT64_MAX, "full-map clearing scale needs arbitrary precision backend");
  for (unsigned b : p.beta) need(scale * b <= UINT64_MAX, "output numerator needs more than uint64");
  return uint64_t(scale);
}
static uint64_t audit_seed(const Problem& p, const std::vector<uint64_t>& seed, uint64_t d) {
  need(seed.size() == uint64_t(p.vertices.size()) * p.G, "compatible seed shape mismatch");
  uint64_t divisor = d;
  for (unsigned u = 0; u < p.vertices.size(); ++u) for (unsigned g = 0; g < p.G; ++g) {
    uint64_t value = seed[uint64_t(u) * p.G + g];
    need(Wide(value) <= Wide(d) * p.beta[g], "seed outside exact RHS bound"); divisor = std::gcd(divisor, value);
  }
  need(divisor == 1, "seed clearing scale is not minimal");
  for (unsigned atom = 0; atom <= p.n; ++atom) for (unsigned g = 0; g < p.G; ++g)
    need(Wide(seed[uint64_t(p.index[p.boundary[atom]]) * p.G + g]) == ((p.rhs[g] & (1u << atom)) ? Wide(d) * p.beta[g] : 0), "seed occurrence boundary mismatch");
  uint64_t edges = 0;
  for (unsigned i = 0; i < p.L; ++i) for (unsigned u = 0; u < p.vertices.size(); ++u) {
    uint32_t x = p.vertices[u]; if (x & (1u << i)) continue;
    int32_t v = p.index[x | (1u << i)]; if (v < 0) continue;
    Wide distance = 0;
    for (unsigned g = 0; g < p.G; ++g) {
      uint64_t a = seed[uint64_t(u) * p.G + g], b = seed[uint64_t(v) * p.G + g];
      distance += a > b ? a - b : b - a;
    }
    need(distance <= Wide(d) * p.alpha[i], "compatible seed edge violation"); ++edges;
  }
  return edges;
}
static std::vector<uint64_t> reconstruct(const Problem& p, const std::vector<uint64_t>& seed, uint64_t d, uint64_t t) {
  std::vector<uint64_t> table(uint64_t(p.N) * p.G);
  uint64_t factor = p.normalizer / (t / d);
  for (uint32_t x = 0; x < p.N; ++x) {
    uint64_t* out = p.G ? table.data() + uint64_t(x) * p.G : nullptr;
    int32_t saved = p.index[x];
    if (saved >= 0) {
      for (unsigned g = 0; g < p.G; ++g) out[g] = uint64_t(Wide(seed[uint64_t(saved) * p.G + g]) * (t / d));
      continue;
    }
    unsigned mass[25]{}; uint64_t q[25]{}, levels[26]{}; Wide accumulator[63]{};
    for (unsigned i = 0; i < p.L; ++i) mass[i] = (x & (1u << i)) ? p.alpha[i] : 0;
    for (auto r : p.disjoint) { unsigned a = std::min(mass[r.i], mass[r.j]); mass[r.i] -= a; mass[r.j] -= a; }
    for (auto r : p.nested) { unsigned a = std::min(mass[r.i], p.alpha[r.j] - mass[r.j]); mass[r.i] -= a; mass[r.j] += a; }
    for (unsigned i = 0; i < p.L; ++i) {
      need(mass[i] <= p.alpha[i], "transport capacity violation");
      q[i] = uint64_t(Wide(mass[i]) * (p.normalizer / p.alpha[i])); levels[i] = q[i];
    }
    for (auto r : p.disjoint) need(!mass[r.i] || !mass[r.j], "transport disjoint conflict");
    for (auto r : p.nested) need(!mass[r.i] || mass[r.j] == p.alpha[r.j], "transport nesting conflict");
    levels[p.L] = p.normalizer; std::sort(levels, levels + p.L + 1);
    uint64_t previous = 0;
    for (unsigned k = 0; k <= p.L; ++k) {
      uint64_t level = levels[k]; if (level == previous) continue;
      uint32_t endpoint = 0;
      for (unsigned i = 0; i < p.L; ++i) if (q[i] >= level) endpoint |= 1u << i;
      int32_t at = p.index[endpoint]; need(at >= 0, "threshold endpoint outside complete C");
      for (unsigned g = 0; g < p.G; ++g) accumulator[g] += Wide(level - previous) * seed[uint64_t(at) * p.G + g];
      previous = level;
    }
    need(previous == p.normalizer, "threshold weights do not sum to one");
    for (unsigned g = 0; g < p.G; ++g) {
      need(accumulator[g] % factor == 0, "nonintegral numerator at derived clearing scale");
      Wide value = accumulator[g] / factor;
      need(value <= Wide(t) * p.beta[g] && value <= UINT64_MAX, "full-map numerator out of bounds"); out[g] = uint64_t(value);
    }
  }
  return table;
}
static uint64_t audit_full(const Problem& p, const std::vector<uint64_t>& table, uint64_t t) {
  for (uint32_t x = 0; x < p.N; ++x) for (unsigned g = 0; g < p.G; ++g)
    need(Wide(table[uint64_t(x) * p.G + g]) <= Wide(t) * p.beta[g], "full-map bound violation");
  for (unsigned atom = 0; atom <= p.n; ++atom) for (unsigned g = 0; g < p.G; ++g)
    need(Wide(table[uint64_t(p.boundary[atom]) * p.G + g]) == ((p.rhs[g] & (1u << atom)) ? Wide(t) * p.beta[g] : 0), "full-map occurrence mismatch");
  uint64_t edges = 0;
  for (unsigned i = 0; i < p.L; ++i) {
    uint32_t side = 1u << i;
    for (uint32_t block = 0; block < p.N; block += 2 * side) for (uint32_t x = block; x < block + side; ++x) {
      Wide distance = 0;
      for (unsigned g = 0; g < p.G; ++g) {
        uint64_t a = table[uint64_t(x) * p.G + g], b = table[uint64_t(x + side) * p.G + g];
        distance += a > b ? a - b : b - a;
      }
      need(distance <= Wide(t) * p.alpha[i], "full original cube edge violation"); ++edges;
    }
  }
  need(edges == uint64_t(p.L) * (p.N / 2), "incomplete full edge coverage"); return edges;
}
static unsigned pop(Wide v) { return __builtin_popcountll(uint64_t(v)) + __builtin_popcountll(uint64_t(v >> 64)); }
static Wide packed_at(const std::vector<unsigned char>& bytes, unsigned r, uint32_t x) {
  uint64_t bit = uint64_t(x) * r; Wide value = 0;
  unsigned count = (r + (bit & 7) + 7) / 8;
  for (unsigned k = 0; k < count; ++k) value |= Wide(bytes[(bit >> 3) + k]) << (8 * k);
  value >>= bit & 7;
  return r ? value & ((Wide(1) << r) - 1) : 0;
}
static std::vector<uint64_t> original_seed(const Problem& p, const std::vector<unsigned char>& bytes) {
  need(p.R <= 120, "original Boolean row requires wider packed auditor");
  uint64_t bits = uint64_t(p.N) * p.R;
  need(bytes.size() == (bits + 7) / 8, "original packed byte length mismatch");
  if (bits % 8) need(!(bytes.back() >> (bits % 8)), "original packed padding is nonzero");
  std::vector<Wide> map(p.N), masks;
  unsigned offset = 0;
  for (unsigned b : p.beta) { masks.push_back(((Wide(1) << b) - 1) << offset); offset += b; }
  for (uint32_t x = 0; x < p.N; ++x) map[x] = packed_at(bytes, p.R, x);
  for (unsigned atom = 0; atom <= p.n; ++atom) {
    Wide expected = 0;
    for (unsigned g = 0; g < p.G; ++g) if (p.rhs[g] & (1u << atom)) expected |= masks[g];
    need(map[p.boundary[atom]] == expected, "original Boolean occurrence mismatch");
  }
  uint64_t edges = 0;
  for (unsigned i = 0; i < p.L; ++i) {
    uint32_t side = 1u << i;
    for (uint32_t block = 0; block < p.N; block += 2 * side) for (uint32_t x = block; x < block + side; ++x) {
      need(pop(map[x] ^ map[x + side]) <= p.alpha[i], "original Boolean cube edge violation"); ++edges;
    }
  }
  need(edges == uint64_t(p.L) * (p.N / 2), "incomplete original Boolean edge coverage");
  std::vector<uint64_t> result(uint64_t(p.vertices.size()) * p.G);
  for (unsigned u = 0; u < p.vertices.size(); ++u) for (unsigned g = 0; g < p.G; ++g)
    result[uint64_t(u) * p.G + g] = pop(map[p.vertices[u]] & masks[g]);
  return result;
}
static void reply(const std::string& json, const std::vector<uint64_t>& rows, const std::vector<uint64_t>& queries) {
  put(json.size(), 4); put(rows.size() * 8, 8); put(queries.size() * 8, 4);
  std::cout.write(json.data(), json.size());
  for (uint64_t value : rows) put(value, 8);
  for (uint64_t value : queries) put(value, 8);
  std::cout.flush();
}
int main() {
  std::ios::sync_with_stdio(false); std::cin.tie(nullptr);
  try {
    while (std::cin.peek() != EOF) {
      auto start = std::chrono::steady_clock::now(); char magic[8];
      need(bool(std::cin.read(magic, 8)) && std::string(magic, 8) == "HECCRP01", "invalid request magic");
      unsigned id = get(4), n = get(4), mode = get(4), dimensions = get(4);
      uint64_t raw_bytes = get(8); unsigned count = get(4); uint64_t d = get(8), t = get(8); unsigned query_count = get(4);
      need(dimensions <= 63 && mode <= 1 && query_count <= 64 && raw_bytes <= uint64_t(1) * 1024 * 1024 * 1024, "unsafe request dimensions");
      std::vector<int32_t> coefficients(dimensions);
      for (auto& value : coefficients) { uint32_t bits = get(4); std::memcpy(&value, &bits, 4); }
      Problem p(n, coefficients);
      need(count == p.vertices.size() && t == scale_for(p, d), "misbound coverage or clearing scale");
      std::vector<uint32_t> queries(query_count);
      for (auto& x : queries) { x = get(4); need(x < p.N, "query outside source cube"); }
      std::vector<uint64_t> seed, query_values;
      if (mode == 0) {
        need(raw_bytes == uint64_t(count) * p.G * 8, "scaled seed length mismatch");
        seed.resize(uint64_t(count) * p.G); for (auto& value : seed) value = get(8);
      } else {
        need(d == 1 && query_count == 0 && raw_bytes == (uint64_t(p.N) * p.R + 7) / 8, "invalid original packed shape");
        std::vector<unsigned char> raw(raw_bytes);
        need(!raw_bytes || bool(std::cin.read(reinterpret_cast<char*>(raw.data()), raw_bytes)), "truncated original map");
        seed = original_seed(p, raw);
      }
      uint64_t seed_edges = audit_seed(p, seed, d), edges = uint64_t(p.L) * (p.N / 2);
      if (mode == 0) {
        auto table = reconstruct(p, seed, d, t); edges = audit_full(p, table, t);
        for (uint32_t x : queries) for (unsigned g = 0; g < p.G; ++g) query_values.push_back(table[uint64_t(x) * p.G + g]);
      }
      auto micros = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - start).count();
      std::ostringstream out;
      out << "{\"ok\":true,\"index\":" << id << ",\"n\":" << n << ",\"L\":" << p.L << ",\"G\":" << p.G
          << ",\"R\":" << p.R << ",\"seed_vertices\":" << count << ",\"seed_edges\":" << seed_edges
          << ",\"checked_vertices\":" << p.N << ",\"checked_edges\":" << edges << ",\"seed_scale\":\"" << d
          << "\",\"clearing_scale\":\"" << t << "\",\"scope\":\"" << (mode ? "original-Boolean-cube-all-edges" : "original-cube-all-edges")
          << "\",\"native_microseconds\":" << micros << ",\"arithmetic\":\"uint64-values-uint128-sums\"}";
      reply(out.str(), mode ? seed : std::vector<uint64_t>{}, query_values);
    }
    return 0;
  } catch (const std::exception& error) {
    std::string message = error.what();
    for (char& c : message) if (c == '"' || c == '\\' || c < ' ') c = '?';
    reply("{\"ok\":false,\"error\":\"" + message + "\"}", {}, {}); return 1;
  }
}
