// Opt-in bounded-memory prototype. No live/frozen binary is changed.
// Reuse the exact independent geometry/seed/protocol/reference implementation.
// The candidate accepts only reconstructed standard proofs (mode 0).
#define main hec_full_table_reference_main
#include "audit_wide.cpp"
#undef main

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
      at(first + offset, values.data() + uint64_t(offset) * p.G);
  }
};

static void exact_edge(const Problem& p, unsigned axis, uint64_t scale, const uint64_t* a, const uint64_t* b) {
  Wide distance = 0;
  for (unsigned g = 0; g < p.G; ++g) distance += a[g] > b[g] ? a[g] - b[g] : b[g] - a[g];
  need(distance <= Wide(scale) * p.alpha[axis], "full original cube edge violation");
}

struct TiledResult { uint64_t edges, vertices, working_bytes, evaluations; };
static TiledResult tiled_audit(PointEvaluator& evaluator, uint64_t limit, std::vector<uint64_t>& query_values,
                               const std::vector<uint32_t>& queries) {
  const Problem& p = evaluator.p;
  need(p.G && uint64_t(p.G) * 16 <= limit, "working budget cannot hold two exact rows");
  unsigned low_axes = 0;
  while (low_axes < p.L && uint64_t(2) * (uint64_t(1) << (low_axes + 1)) * p.G * 8 <= limit) ++low_axes;
  uint32_t width = 1u << low_axes;
  std::vector<uint64_t> base(uint64_t(width) * p.G), adjacent(base.size());
  uint64_t edges = 0, checked_vertices = 0;
  for (uint32_t first = 0; first < p.N; first += width) {
    evaluator.range(first, width, base);
    for (uint32_t x = 0; x < width; ++x) for (unsigned g = 0; g < p.G; ++g)
      need(Wide(base[uint64_t(x) * p.G + g]) <= Wide(evaluator.t) * p.beta[g], "full-map bound violation");
    checked_vertices += width;
    // Every low-axis edge belongs to exactly this base tile.
    for (unsigned axis = 0; axis < low_axes; ++axis) {
      uint32_t side = 1u << axis;
      for (uint32_t block = 0; block < width; block += 2 * side) for (uint32_t x = block; x < block + side; ++x) {
        exact_edge(p, axis, evaluator.t, base.data() + uint64_t(x) * p.G,
                   base.data() + uint64_t(x + side) * p.G);
        ++edges;
      }
    }
    // Every high-axis edge belongs to its bit-zero endpoint tile, once.
    for (unsigned axis = low_axes; axis < p.L; ++axis) if (!(first & (1u << axis))) {
      evaluator.range(first | (1u << axis), width, adjacent);
      for (uint32_t x = 0; x < width; ++x) {
        exact_edge(p, axis, evaluator.t, base.data() + uint64_t(x) * p.G, adjacent.data() + uint64_t(x) * p.G);
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
        auto table = reconstruct(p, seed, d, t);
        result = {audit_full(p, table, t), p.N, full_bytes, p.N};
        for (uint32_t x : queries) for (unsigned g = 0; g < p.G; ++g)
          query_values.push_back(table[uint64_t(x) * p.G + g]);
      }
      auto micros = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - start).count();
      std::ostringstream out;
      out << "{\"ok\":true,\"index\":" << id << ",\"n\":" << n << ",\"L\":" << p.L << ",\"G\":" << p.G
          << ",\"R\":" << p.R << ",\"seed_vertices\":" << count << ",\"seed_edges\":" << seed_edges
          << ",\"checked_vertices\":" << result.vertices << ",\"checked_edges\":" << result.edges
          << ",\"seed_scale\":\"" << d << "\",\"clearing_scale\":\"" << t
          << "\",\"scope\":\"original-cube-all-edges\",\"native_microseconds\":" << micros
          << ",\"arithmetic\":\"uint64-values-uint128-sums\",\"working_layout\":\"" << (tiled ? "exact-tiles/1" : "full-table/1")
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
