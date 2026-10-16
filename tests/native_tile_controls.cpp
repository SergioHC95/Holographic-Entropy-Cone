// Independently enumerate the edge SET, not just its cardinality, for every
// low/high split of all cubes through dimension 12 using production TileVisit.
#define main hec_cube_protocol_main
#include "../src/hec/_native/verify.cpp"
#undef main

int main() {
  {
    Problem p(2, {2, 3, -1});
    std::vector<uint64_t> seed(uint64_t(p.vertices.size()) * p.G);
    for (auto scales : std::vector<std::pair<uint64_t, uint64_t>>{{0, 0}, {1, 1}, {UINT64_MAX, UINT64_MAX}}) {
      bool rejected = false;
      try { PointEvaluator evaluator(p, seed, scales.first, scales.second); }
      catch (const std::exception&) { rejected = true; }
      need(rejected, "derived scale law was not enforced before eliminating division");
    }
    PointEvaluator valid(p, seed, 1, 6);
    need(valid.t == 6, "valid derived scale rejected");
  }
  for (unsigned dimensions = 0; dimensions <= 12; ++dimensions) {
    uint32_t vertices = 1u << dimensions;
    for (unsigned low = 0; low <= dimensions; ++low) {
      unsigned high = dimensions - low;
      uint32_t width = 1u << low, tiles = vertices / width;
      std::vector<unsigned> edges(uint64_t(vertices) * dimensions), visits(vertices);
      uint64_t evaluations = 1;
      auto edge = [&](uint32_t a, uint32_t b, unsigned axis) {
        need(a < vertices && b < vertices && (a ^ b) == (1u << axis), "not an original cube edge");
        uint32_t owner = a & ~(1u << axis);
        need(++edges[uint64_t(owner) * dimensions + axis] == 1, "duplicate original cube edge");
      };
      uint32_t retained = 0;
      for (uint32_t step = 0; step < tiles; ++step) {
        TileVisit visit(step, high);
        need(visit.current == retained && visit.current < tiles, "wrong retained base tile");
        for (uint32_t x = 0; x < width; ++x) {
          uint32_t original = visit.current * width + x;
          need(++visits[original] == 1, "duplicate base vertex");
          for (unsigned axis = 0; axis < low; ++axis)
            if (!(x & (1u << axis))) edge(original, original ^ (1u << axis), axis);
        }
        for (unsigned axis = 0; axis < high; ++axis) if (visit.owns_nonpath(axis)) {
          ++evaluations;
          for (uint32_t x = 0; x < width; ++x)
            edge(visit.current * width + x, (visit.current ^ (1u << axis)) * width + x, low + axis);
        }
        if (visit.next < tiles) {
          uint32_t changed = visit.current ^ visit.next;
          need(changed && !(changed & (changed - 1)), "path transition is not one cube axis");
          unsigned axis = unsigned(__builtin_ctz(changed));
          ++evaluations;
          for (uint32_t x = 0; x < width; ++x)
            edge(visit.current * width + x, visit.next * width + x, low + axis);
          retained = visit.next;
        }
      }
      // Independent axis-major enumeration is the expected edge set.
      for (uint32_t x = 0; x < vertices; ++x) {
        need(visits[x] == 1, "original cube vertex omitted");
        for (unsigned axis = 0; axis < dimensions; ++axis)
          need(edges[uint64_t(x) * dimensions + axis] == unsigned(!(x & (1u << axis))),
               "original cube edge omitted or assigned to both endpoints");
      }
      need(evaluations == uint64_t(high) * (tiles / 2) + 1, "tile reconstruction bound changed");
    }
  }
}
