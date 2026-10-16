// Differential arithmetic controls for the production interval propagator.
// Scalar formulas below are test oracles, never a second acceptance backend.
#define HEC_CLOSURE_LIBRARY
#include "../src/hec/_native/closure.cpp"

static uint64_t random_state = 982451653;
static unsigned sample(unsigned cap) {
  random_state = random_state * 6364136223846793005ULL + 1442695040888963407ULL;
  return unsigned(random_state % (cap + 1));
}
static void install(Engine& e, unsigned u, const std::vector<unsigned>& lo, const std::vector<unsigned>& hi) {
  e.row_unknown[u] = e.row_width[u] = 0;
  e.low_bits[u] = e.high_bits[u] = e.open_groups[u] = 0;
  for (unsigned g = 0; g < e.p.G; ++g) {
    e.low[u*e.p.G+g] = lo[g]; e.high[u*e.p.G+g] = hi[g];
    e.row_unknown[u] += lo[g] != hi[g]; e.row_width[u] += hi[g] - lo[g];
    if (lo[g] != hi[g]) e.open_groups[u] |= uint64_t(1) << g;
    e.low_bits[u] |= ((uint64_t(1) << lo[g]) - 1) << e.offsets[g];
    e.high_bits[u] |= ((uint64_t(1) << hi[g]) - 1) << e.offsets[g];
  }
}
static void check_row(const Engine& e, unsigned u, const std::vector<unsigned>& lo, const std::vector<unsigned>& hi) {
  unsigned unknown = 0, width = 0;
  uint64_t low_bits = 0, high_bits = 0, open = 0;
  for (unsigned g = 0; g < e.p.G; ++g) {
    need(e.low[u*e.p.G+g] == lo[g] && e.high[u*e.p.G+g] == hi[g], "interval inference changed");
    unknown += lo[g] != hi[g]; width += hi[g] - lo[g];
    if (lo[g] != hi[g]) open |= uint64_t(1) << g;
    low_bits |= ((uint64_t(1) << lo[g]) - 1) << e.offsets[g];
    high_bits |= ((uint64_t(1) << hi[g]) - 1) << e.offsets[g];
  }
  need(e.row_unknown[u] == unknown && e.row_width[u] == width && e.open_groups[u] == open &&
       e.low_bits[u] == low_bits && e.high_bits[u] == high_bits, "stale interval/priority cache");
}
int main() {
  for (auto caps : std::vector<std::vector<int>>{{1,1,1,1},{2,3,4,5},{15,16,16,16}}) {
    Problem p(3, {-caps[0],-caps[1],-caps[2],3,3,3,-caps[3]});
    Engine e(p, 0, 0, true, {});
    for (unsigned test = 0; test < 5000; ++test) {
      std::vector<unsigned> al(p.G), ah(p.G), bl(p.G), bh(p.G), minimum(p.G);
      unsigned total = 0;
      for (unsigned g = 0; g < p.G; ++g) {
        unsigned a = sample(p.beta[g]), b = sample(p.beta[g]); al[g] = std::min(a,b); ah[g] = std::max(a,b);
        a = sample(p.beta[g]); b = sample(p.beta[g]); bl[g] = std::min(a,b); bh[g] = std::max(a,b);
        minimum[g] = unsigned(std::max({0,int(al[g])-int(bh[g]),int(bl[g])-int(ah[g])}));
        total += minimum[g];
      }
      unsigned budget = sample(63);
      install(e, 0, al, ah); install(e, 1, bl, bh);
      bool rejected = false;
      try { e.edge(0,1,budget); } catch (const std::exception&) { rejected = true; }
      need(rejected == (total > budget), "edge feasibility changed");
      if (!rejected) {
        auto cl = al, ch = ah, dl = bl, dh = bh;
        for (unsigned g = 0; g < p.G; ++g) {
          int slack = int(budget-total+minimum[g]);
          cl[g] = unsigned(std::max(int(al[g]),int(bl[g])-slack));
          ch[g] = unsigned(std::min(int(ah[g]),int(bh[g])+slack));
          dl[g] = unsigned(std::max(int(bl[g]),int(al[g])-slack));
          dh[g] = unsigned(std::min(int(bh[g]),int(ah[g])+slack));
        }
        check_row(e,0,cl,ch); check_row(e,1,dl,dh);
      }
      install(e,0,al,ah);
      uint64_t below = 0, above = 0;
      for (unsigned g = 0; g < p.G; ++g) {
        below |= ((uint64_t(1) << bl[g])-1) << e.offsets[g];
        above |= ((uint64_t(1) << bh[g])-1) << e.offsets[g];
      }
      rejected = false;
      bool retired = false;
      try { retired = e.box(0,budget,below,above,[&](unsigned g){return bl[g];},[&](unsigned g){return bh[g];}); }
      catch (const std::exception&) { rejected = true; }
      need(rejected == (total > budget), "box feasibility changed");
      if (!rejected) {
        auto cl = al, ch = ah;
        unsigned maximum = 0;
        for (unsigned g = 0; g < p.G; ++g) {
          int slack = int(budget-total+minimum[g]);
          cl[g] = unsigned(std::max(int(al[g]),int(bl[g])-slack));
          ch[g] = unsigned(std::min(int(ah[g]),int(bh[g])+slack));
          maximum += unsigned(std::max({0,int(bl[g])-int(al[g]),int(ah[g])-int(bh[g])}));
        }
        need(!retired || maximum <= budget, "nonredundant constraint retired");
        check_row(e,0,cl,ch);
      }
    }
  }
}
