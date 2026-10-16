// Independent exact verifier for the sole standardized full-map pipeline.
// One point rule is shared by full and bounded-memory evaluation.
// Mode 0 only: canonical proof decoding belongs to the strict package reader.
// --working-bytes limits primary output buffers, not total process RSS.
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
  bool uniform_alpha = true;
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
    uniform_alpha = alpha.empty() || std::all_of(alpha.begin(), alpha.end(), [&](unsigned a) { return a == alpha[0]; });
    need(L <= 25 && G <= 63, "geometry needs a larger independent auditor");
    N = 1u << L;
    // Supported cardinality allowance, not an instruction to allocate the full table.
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
    // Evaluate all binary clauses with adjacency masks, independently of the
    // recursive enumeration, rather than scanning every pair at every point.
    std::vector<uint32_t> forbidden(L), required(L);
    for (auto r : disjoint) forbidden[r.i] |= 1u << r.j;
    for (auto r : nested) required[r.i] |= 1u << r.j;
    uint64_t complete = 0;
    for (uint32_t x = 0; x < N; ++x) {
      bool valid = true;
      for (uint32_t enabled = x; enabled; enabled &= enabled - 1) {
        unsigned i = unsigned(__builtin_ctz(enabled));
        if ((x & forbidden[i]) || (required[i] & ~x)) { valid = false; break; }
      }
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
// A count q becomes q leading one-bits in its group's disjoint bit interval.
// The Hamming distance of two such rows is EXACTLY their count L1 distance.
// Small cleared ranges therefore need one/two popcounts per original edge.
// Packing happens in place only when it reduces row width, after exact bounds.
struct RowMetric {
  const Problem& p;
  uint64_t scale;
  unsigned words = 0;
  bool narrow_sum;
  RowMetric(const Problem& problem, uint64_t t) : p(problem), scale(t), narrow_sum(Wide(t) * p.R <= UINT64_MAX) {
    Wide bits = Wide(t) * p.R;
    if (bits && bits <= 128) {
      unsigned count = (unsigned(bits) + 63) / 64;
      if (count < p.G) words = count;
    }
  }
  unsigned stride() const { return words ? words : p.G; }
  void pack(std::vector<uint64_t>& values, uint32_t count) const {
    for (uint32_t x = 0; x < count; ++x) {
      uint64_t packed[2]{};
      unsigned start = 0;
      for (unsigned g = 0; g < p.G; ++g) {
        uint64_t q = values[uint64_t(x) * p.G + g];
        need(Wide(q) <= Wide(scale) * p.beta[g], "full-map bound violation");
        if (words) {
          if (q) {
            unsigned word = start / 64, shift = start % 64;
            unsigned first = std::min(unsigned(q), 64 - shift);
            uint64_t mask = first == 64 ? UINT64_MAX : (uint64_t(1) << first) - 1;
            packed[word] |= mask << shift;
            if (q > first) {
              unsigned left = unsigned(q) - first;
              packed[word + 1] |= left == 64 ? UINT64_MAX : (uint64_t(1) << left) - 1;
            }
          }
          start += unsigned(scale * p.beta[g]);
        }
      }
      // All source cells for this row were read before any overlapping write.
      // words < G ensures no write can reach a later unread source row.
      for (unsigned w = 0; w < words; ++w) values[uint64_t(x) * words + w] = packed[w];
    }
  }
  Wide distance(const uint64_t* a, const uint64_t* b) const {
    if (words) {
      unsigned total = unsigned(__builtin_popcountll(a[0] ^ b[0]));
      if (words == 2) total += unsigned(__builtin_popcountll(a[1] ^ b[1]));
      return total;
    }
    if (narrow_sum) {
      // Bounds were checked first: sum |a-b| <= scale*sum(beta), so no wrap.
      uint64_t total = 0;
      for (unsigned g = 0; g < p.G; ++g) total += a[g] > b[g] ? a[g] - b[g] : b[g] - a[g];
      return total;
    }
    Wide total = 0;
    for (unsigned g = 0; g < p.G; ++g) total += a[g] > b[g] ? a[g] - b[g] : b[g] - a[g];
    return total;
  }
  void edge(unsigned axis, const uint64_t* a, const uint64_t* b) const {
    need(distance(a, b) <= Wide(scale) * p.alpha[axis], "full original cube edge violation");
  }
};
static uint64_t audit_full(const Problem& p, std::vector<uint64_t>& table, uint64_t t) {
  for (unsigned atom = 0; atom <= p.n; ++atom) for (unsigned g = 0; g < p.G; ++g)
    need(Wide(table[uint64_t(p.boundary[atom]) * p.G + g]) == ((p.rhs[g] & (1u << atom)) ? Wide(t) * p.beta[g] : 0), "full-map occurrence mismatch");
  RowMetric metric(p, t);
  metric.pack(table, p.N);
  unsigned stride = metric.stride();
  uint64_t edges = 0;
  for (unsigned i = 0; i < p.L; ++i) {
    uint32_t side = 1u << i;
    for (uint32_t block = 0; block < p.N; block += 2 * side) for (uint32_t x = block; x < block + side; ++x) {
      metric.edge(i, stride ? table.data() + uint64_t(x) * stride : nullptr,
                  stride ? table.data() + uint64_t(x + side) * stride : nullptr);
      ++edges;
    }
  }
  need(edges == uint64_t(p.L) * (p.N / 2), "incomplete full edge coverage"); return edges;
}
static void reply(const std::string& json, const std::vector<uint64_t>& rows, const std::vector<uint64_t>& queries) {
  put(json.size(), 4); put(rows.size() * 8, 8); put(queries.size() * 8, 4);
  std::cout.write(json.data(), json.size());
  for (uint64_t value : rows) put(value, 8);
  for (uint64_t value : queries) put(value, 8);
  std::cout.flush();
}
struct PointEvaluator {
  const Problem& p;
  const std::vector<uint64_t>& seed;
  uint64_t d, t, factor;
  uint64_t evaluations = 0;
  PointEvaluator(const Problem& problem, const std::vector<uint64_t>& values, uint64_t scale, uint64_t full)
      : p(problem), seed(values), d(scale), t(full), factor(p.normalizer / (t / d)) {}
  void at(uint32_t x, uint64_t* out) {
    ++evaluations;
    int32_t saved = p.index[x];
    if (saved >= 0) {
      for (unsigned g = 0; g < p.G; ++g) out[g] = uint64_t(Wide(seed[uint64_t(saved) * p.G + g]) * (t / d));
      return;
    }
    if (p.uniform_alpha) {
      // Equal capacities keep every transported mass at zero or capacity.
      // The common-threshold integral therefore has one Boolean endpoint.
      uint32_t endpoint = x;
      for (auto r : p.disjoint) {
        uint32_t pair = (1u << r.i) | (1u << r.j);
        if ((endpoint & pair) == pair) endpoint &= ~pair;
      }
      for (auto r : p.nested) {
        uint32_t a = 1u << r.i, b = 1u << r.j;
        if ((endpoint & a) && !(endpoint & b)) endpoint = (endpoint & ~a) | b;
      }
      int32_t at = p.index[endpoint];
      need(at >= 0 && t == d, "uniform retraction outside exact compatible domain");
      for (unsigned g = 0; g < p.G; ++g) out[g] = seed[uint64_t(at) * p.G + g];
      return;
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
      need(value <= Wide(t) * p.beta[g] && value <= UINT64_MAX, "full-map numerator out of bounds");
      out[g] = uint64_t(value);
    }
  }
  void range(uint32_t first, uint32_t count, std::vector<uint64_t>& values) {
    for (uint32_t offset = 0; offset < count; ++offset)
      at(first + offset, p.G ? values.data() + uint64_t(offset) * p.G : nullptr);
  }
};

struct TiledResult { uint64_t edges, vertices, working_bytes, evaluations; };
static TiledResult tiled_audit(PointEvaluator& evaluator, uint64_t limit, std::vector<uint64_t>& query_values,
                               const std::vector<uint32_t>& queries) {
  const Problem& p = evaluator.p;
  need(p.G && uint64_t(p.G) * 16 <= limit, "working budget cannot hold two exact rows");
  unsigned low_axes = 0;
  while (low_axes < p.L && uint64_t(2) * (uint64_t(1) << (low_axes + 1)) * p.G * 8 <= limit) ++low_axes;
  uint32_t width = 1u << low_axes;
  std::vector<uint64_t> base(uint64_t(width) * p.G), adjacent(base.size());
  RowMetric metric(p, evaluator.t);
  unsigned stride = metric.stride();
  uint64_t edges = 0, checked_vertices = 0;
  for (uint32_t first = 0; first < p.N; first += width) {
    evaluator.range(first, width, base);
    metric.pack(base, width);
    checked_vertices += width;
    // Every low-axis edge belongs to exactly this base tile.
    for (unsigned axis = 0; axis < low_axes; ++axis) {
      uint32_t side = 1u << axis;
      for (uint32_t block = 0; block < width; block += 2 * side) for (uint32_t x = block; x < block + side; ++x) {
        metric.edge(axis, base.data() + uint64_t(x) * stride,
                    base.data() + uint64_t(x + side) * stride);
        ++edges;
      }
    }
    // Every high-axis edge belongs to its bit-zero endpoint tile, once.
    for (unsigned axis = low_axes; axis < p.L; ++axis) if (!(first & (1u << axis))) {
      evaluator.range(first | (1u << axis), width, adjacent);
      metric.pack(adjacent, width);
      for (uint32_t x = 0; x < width; ++x) {
        metric.edge(axis, base.data() + uint64_t(x) * stride, adjacent.data() + uint64_t(x) * stride);
        ++edges;
      }
    }
  }
  std::vector<uint64_t> row(p.G);
  for (unsigned atom = 0; atom <= p.n; ++atom) {
    evaluator.at(p.boundary[atom], row.data());
    for (unsigned g = 0; g < p.G; ++g)
      need(Wide(row[g]) == ((p.rhs[g] & (1u << atom)) ? Wide(evaluator.t) * p.beta[g] : 0), "full-map occurrence mismatch");
  }
  for (uint32_t x : queries) {
    evaluator.at(x, row.data()); query_values.insert(query_values.end(), row.begin(), row.end());
  }
  need(checked_vertices == p.N && edges == uint64_t(p.L) * (p.N / 2), "incomplete full tiled coverage");
  uint64_t working_bytes = (uint64_t(base.size()) + adjacent.size()) * 8;
  need(working_bytes <= limit, "tiled row storage exceeded working budget");
  return {edges, checked_vertices, working_bytes, evaluator.evaluations};
}

int main(int argc, char** argv) {
  std::ios::sync_with_stdio(false); std::cin.tie(nullptr);
  try {
    uint64_t limit = uint64_t(256) * 1024 * 1024;
    if (argc != 1) {
      need(argc == 3 && std::string(argv[1]) == "--working-bytes", "only trusted --working-bytes configuration is accepted");
      std::string value(argv[2]);
      need(!value.empty() && value[0] != '0' && value.find_first_not_of("0123456789") == std::string::npos,
           "working byte budget must be a canonical positive integer");
      limit = std::stoull(value);
      need(limit <= uint64_t(30) * 1024 * 1024 * 1024, "working budget exceeds unchanged native allowance");
    }
    while (std::cin.peek() != EOF) {
      auto start = std::chrono::steady_clock::now(); char magic[8];
      need(bool(std::cin.read(magic, 8)) && std::string(magic, 8) == "HECCRP01", "invalid request magic");
      unsigned id = get(4), n = get(4), mode = get(4), dimensions = get(4);
      uint64_t raw_bytes = get(8); unsigned count = get(4); uint64_t d = get(8), t = get(8); unsigned query_count = get(4);
      need(dimensions <= 63 && mode == 0 && query_count <= 64 && raw_bytes <= uint64_t(1) * 1024 * 1024 * 1024,
           "unsafe or nonstandard proof request");
      std::vector<int32_t> coefficients(dimensions);
      for (auto& value : coefficients) { uint32_t bits = get(4); std::memcpy(&value, &bits, 4); }
      Problem p(n, coefficients);
      need(count == p.vertices.size() && t == scale_for(p, d), "misbound coverage or clearing scale");
      std::vector<uint32_t> queries(query_count);
      for (auto& x : queries) { x = get(4); need(x < p.N, "query outside source cube"); }
      need(raw_bytes == uint64_t(count) * p.G * 8, "scaled seed length mismatch");
      std::vector<uint64_t> seed(uint64_t(count) * p.G), query_values;
      for (auto& value : seed) value = get(8);
      uint64_t seed_edges = audit_seed(p, seed, d), full_bytes = uint64_t(p.N) * p.G * 8;
      bool tiled = full_bytes > limit;
      TiledResult result{};
      if (tiled) {
        PointEvaluator evaluator(p, seed, d, t);
        result = tiled_audit(evaluator, limit, query_values, queries);
      } else {
        PointEvaluator evaluator(p, seed, d, t);
        std::vector<uint64_t> table(uint64_t(p.N) * p.G);
        evaluator.range(0, p.N, table);
        for (uint32_t x : queries) for (unsigned g = 0; g < p.G; ++g)
          query_values.push_back(table[uint64_t(x) * p.G + g]);
        result = {audit_full(p, table, t), p.N, full_bytes, evaluator.evaluations};
      }
      auto micros = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - start).count();
      std::ostringstream out;
      out << "{\"ok\":true,\"index\":" << id << ",\"n\":" << n << ",\"L\":" << p.L << ",\"G\":" << p.G
          << ",\"R\":" << p.R << ",\"seed_vertices\":" << count << ",\"seed_edges\":" << seed_edges
          << ",\"checked_vertices\":" << result.vertices << ",\"checked_edges\":" << result.edges
          << ",\"seed_scale\":\"" << d << "\",\"clearing_scale\":\"" << t
          << "\",\"scope\":\"original-cube-all-edges\",\"native_microseconds\":" << micros
          << ",\"arithmetic\":\"uint64-values-uint128-sums\",\"working_layout\":\"" << (tiled ? "exact-tiles/1" : "full-table/1")
          << "\",\"edge_metric\":\"" << (RowMetric(p, t).words ? "unary-prefix-hamming/1" : "exact-count-l1/1")
          << "\",\"output_row_storage_bytes\":" << result.working_bytes << ",\"output_row_storage_limit\":" << limit
          << ",\"reconstruction_evaluations\":" << result.evaluations << "}";
      reply(out.str(), {}, query_values);
    }
    return 0;
  } catch (const std::exception& error) {
    std::string message = error.what();
    for (char& c : message) if (c == '"' || c == '\\' || c < ' ') c = '?';
    reply("{\"ok\":false,\"error\":\"" + message + "\"}", {}, {}); return 1;
  }
}
