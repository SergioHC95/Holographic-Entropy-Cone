// Independent exact audit of compact cancel/fill proof definitions.
// Rebuild geometry, derive complete C, decode every seed value, reconstruct
// every original source vertex, and check EVERY original cube edge. No floats,
// source Boolean tables, migration receipts, or stored validity claims.
// Build: c++ -O3 -std=c++17 tools/verify_count_proofs.cpp -o verify_count_proofs
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <functional>
#include <iostream>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <chrono>

using Clock = std::chrono::steady_clock;
static void require(bool ok, const char* message) {
  if (!ok) throw std::runtime_error(message);
}
static uint64_t number(unsigned bytes) {
  unsigned char b[8]{};
  require(bytes <= 8 && bool(std::cin.read(reinterpret_cast<char*>(b), bytes)), "truncated request");
  uint64_t value = 0;
  for (unsigned i=0; i<bytes; ++i) value |= uint64_t(b[i]) << (8*i);
  return value;
}
static void put_number(uint64_t value, unsigned bytes) {
  for (unsigned i=0; i<bytes; ++i) std::cout.put(char(value >> (8*i)));
}
struct Relation { unsigned small, large; uint32_t mask; };
struct Geometry {
  unsigned n, L, G, R;
  uint32_t N;
  std::vector<unsigned> lhs, alpha, rhs, beta, widths, offsets;
  std::vector<Relation> disjoint, nested;
  std::vector<uint32_t> boundary;
  std::vector<uint64_t> boundary_bits, group_masks;
  unsigned normalizer=1, scale=1, row_bits=0;
};
static Geometry geometry(unsigned n, const std::vector<int32_t>& coefficients) {
  require(n>=1 && n<=6 && coefficients.size()==(uint32_t(1)<<n)-1, "unsupported party dimension");
  Geometry p{}; p.n=n;
  std::vector<unsigned> supports;
  for (unsigned size=1; size<=n; ++size) {
    std::function<void(unsigned,unsigned,unsigned)> visit = [&](unsigned first,unsigned left,unsigned mask) {
      if (!left) { supports.push_back(mask); return; }
      for (unsigned i=first; i+left<=n; ++i) visit(i+1,left-1,mask|(1u<<i));
    };
    visit(0,size,0);
  }
  unsigned divisor=0;
  for (unsigned i=0; i<coefficients.size(); ++i) {
    int64_t value=coefficients[i];
    divisor=std::gcd(divisor,unsigned(value<0 ? -value : value));
    if (value>0) {
      require(value<=32,"source capacity outside offline auditor range");
      p.lhs.push_back(supports[i]); p.alpha.push_back(unsigned(value));
    } else if (value<0) {
      require(-value<=63,"RHS capacity outside offline auditor range");
      p.rhs.push_back(supports[i]); p.beta.push_back(unsigned(-value));
    }
  }
  require(divisor==0 || divisor==1,"coefficient vector is not primitive");
  p.L=p.lhs.size(); p.G=p.rhs.size();
  require(p.L<=17 && p.G<=63,"source dimension outside exact native auditor range");
  p.N=uint32_t(1)<<p.L;
  p.R=std::accumulate(p.beta.begin(),p.beta.end(),0u);
  require(p.R<=63,"Boolean row outside 63-bit audit range");
  for (unsigned a:p.alpha) {
    uint64_t next=uint64_t(p.normalizer/std::gcd(p.normalizer,a))*a;
    require(next<=65535,"normalizer outside exact bounded auditor range");
    p.normalizer=unsigned(next);
  }
  p.scale=std::all_of(p.alpha.begin(),p.alpha.end(),[&](unsigned a){return a==p.alpha[0];}) ? 1 : p.normalizer;
  for (unsigned cap:p.beta) {
    require(uint64_t(cap)*p.scale<=65535,"output numerator needs wider independent auditor");
    unsigned width=0;
    for (unsigned b=cap;b;b>>=1) ++width;
    p.offsets.push_back(p.row_bits); p.widths.push_back(width); p.row_bits+=width;
  }
  require(uint64_t(p.R)*p.scale<=UINT32_MAX,"distance accumulator overflow");
  for (unsigned i=0;i<p.L;++i) for (unsigned j=0;j<p.L;++j) {
    if (i<j && !(p.lhs[i]&p.lhs[j])) p.disjoint.push_back({i,j,(1u<<i)|(1u<<j)});
    if (p.lhs[i]!=p.lhs[j] && (p.lhs[i]&p.lhs[j])==p.lhs[i]) {
      require(i<j,"source supports not in subset-first order");
      p.nested.push_back({i,j,(1u<<i)|(1u<<j)});
    }
  }
  unsigned offset=0;
  for (unsigned cap:p.beta) {
    p.group_masks.push_back(((uint64_t(1)<<cap)-1)<<offset);
    offset+=cap;
  }
  for (unsigned atom=0;atom<=n;++atom) {
    uint32_t vertex=0; uint64_t image=0;
    for (unsigned i=0;i<p.L;++i) if (p.lhs[i]&(1u<<atom)) vertex|=1u<<i;
    for (unsigned g=0;g<p.G;++g) if (p.rhs[g]&(1u<<atom)) image|=p.group_masks[g];
    for (unsigned k=0;k<p.boundary.size();++k)
      require(vertex!=p.boundary[k] || image==p.boundary_bits[k],"conflicting occurrence boundaries");
    p.boundary.push_back(vertex); p.boundary_bits.push_back(image);
  }
  return p;
}

// The producer uses recursive constraint propagation. The checker below
// independently visits ALL original vertices and applies the defining clauses.
static std::vector<uint32_t> domain_recursive(const Geometry& p) {
  std::vector<uint32_t> predecessor(p.L), conflict(p.L), vertices;
  for (auto pair:p.nested) predecessor[pair.large]|=1u<<pair.small;
  for (auto pair:p.disjoint) {
    conflict[pair.small]|=1u<<pair.large; conflict[pair.large]|=1u<<pair.small;
  }
  std::function<void(int,uint32_t,uint32_t)> visit = [&](int axis,uint32_t zeros,uint32_t value) {
    if (axis<0) { vertices.push_back(value); return; }
    uint32_t lower=(1u<<axis)-1;
    visit(axis-1,(zeros|predecessor[axis])&lower,value);
    if (!(zeros&(1u<<axis))) visit(axis-1,(zeros|conflict[axis])&lower,value|(1u<<axis));
  };
  visit(int(p.L)-1,0,0);
  return vertices;
}
static bool compatible(const Geometry& p,uint32_t vertex) {
  for (auto pair:p.disjoint) if ((vertex&pair.mask)==pair.mask) return false;
  for (auto pair:p.nested)
    if ((vertex&(1u<<pair.small)) && !(vertex&(1u<<pair.large))) return false;
  return true;
}
static unsigned decode_seed_value(const std::vector<unsigned char>& data,uint64_t bit,unsigned width) {
  // Separate exact per-bit decoder, not the producer's accumulator algorithm.
  unsigned value=0;
  for (unsigned k=0;k<width;++k) value|=((data[(bit+k)>>3]>>((bit+k)&7))&1u)<<k;
  return value;
}
struct SeedAudit { std::vector<int32_t> index; std::vector<uint8_t> rows; uint64_t edges=0; };
static SeedAudit audit_seed(const Geometry& p,const std::vector<unsigned char>& payload,
                           const std::vector<uint32_t>& declared) {
  uint64_t bits=uint64_t(declared.size())*p.row_bits;
  require(payload.size()==(bits+7)/8,"seed encoded length mismatch");
  if (bits%8) require(!(payload.back()>>(bits%8)),"seed nonzero padding");
  SeedAudit seed; seed.index.assign(p.N,-1); seed.rows.resize(uint64_t(declared.size())*p.G);
  unsigned position=0;
  for (uint32_t vertex=0;vertex<p.N;++vertex) if (compatible(p,vertex)) {
    require(position<declared.size() && declared[position]==vertex,"compatible coverage/order mismatch");
    seed.index[vertex]=position;
    for (unsigned g=0;g<p.G;++g) {
      unsigned value=decode_seed_value(payload,uint64_t(position)*p.row_bits+p.offsets[g],p.widths[g]);
      require(value<=p.beta[g],"seed count outside exact bound");
      seed.rows[uint64_t(position)*p.G+g]=value;
    }
    ++position;
  }
  require(position==declared.size(),"extra compatible seed rows");
  for (unsigned atom=0;atom<p.boundary.size();++atom) {
    int32_t i=seed.index[p.boundary[atom]];
    require(i>=0,"occurrence missing from seed");
    for (unsigned g=0;g<p.G;++g)
      require(seed.rows[uint64_t(i)*p.G+g]==((p.rhs[g]&(1u<<atom))?p.beta[g]:0),"seed boundary mismatch");
  }
  for (unsigned axis=0;axis<p.L;++axis) {
    uint32_t side=1u<<axis;
    for (uint32_t vertex:declared) if (!(vertex&side)) {
      int32_t j=seed.index[vertex|side];
      if (j<0) continue;
      int32_t i=seed.index[vertex]; unsigned distance=0;
      for (unsigned g=0;g<p.G;++g) {
        int a=seed.rows[uint64_t(i)*p.G+g], b=seed.rows[uint64_t(j)*p.G+g];
        distance+=unsigned(a>b?a-b:b-a);
      }
      require(distance<=p.alpha[axis],"compatible seed edge violation");
      ++seed.edges;
    }
  }
  return seed;
}
struct Reconstruction {
  std::vector<uint16_t> rows; uint64_t changed=0; unsigned minimal_scale=1;
};
static Reconstruction reconstruct(const Geometry& p,const SeedAudit& seed) {
  Reconstruction result; result.rows.resize(uint64_t(p.N)*p.G);
  unsigned divisor=p.scale;
  for (uint32_t vertex=0;vertex<p.N;++vertex) {
    uint16_t* out=p.G ? result.rows.data()+uint64_t(vertex)*p.G : nullptr;
    int32_t saved=seed.index[vertex];
    if (saved>=0) {
      for (unsigned g=0;g<p.G;++g) out[g]=p.scale*seed.rows[uint64_t(saved)*p.G+g];
    } else {
      unsigned mass[63]{}, q[63]{}, levels[64]{}, accumulator[63]{};
      for (unsigned i=0;i<p.L;++i) mass[i]=(vertex&(1u<<i))?p.alpha[i]:0;
      for (auto pair:p.disjoint) {
        unsigned t=std::min(mass[pair.small],mass[pair.large]);
        mass[pair.small]-=t; mass[pair.large]-=t;
      }
      for (auto pair:p.nested) {
        unsigned t=std::min(mass[pair.small],p.alpha[pair.large]-mass[pair.large]);
        mass[pair.small]-=t; mass[pair.large]+=t;
      }
      for (unsigned i=0;i<p.L;++i) {
        require(mass[i]<=p.alpha[i],"transport exceeds source capacity");
        q[i]=mass[i]*(p.normalizer/p.alpha[i]); levels[i]=q[i];
      }
      for (auto pair:p.disjoint) require(!mass[pair.small] || !mass[pair.large],"transport disjoint conflict");
      for (auto pair:p.nested)
        require(!mass[pair.small] || mass[pair.large]==p.alpha[pair.large],"one-pass nesting conflict");
      levels[p.L]=p.normalizer;
      std::sort(levels,levels+p.L+1);
      unsigned previous=0;
      for (unsigned j=0;j<=p.L;++j) {
        unsigned level=levels[j]; if (level==previous) continue;
        uint32_t endpoint=0;
        for (unsigned i=0;i<p.L;++i) if (q[i]>=level) endpoint|=1u<<i;
        int32_t location=seed.index[endpoint];
        require(location>=0,"threshold outside independently verified complete seed");
        unsigned weight=level-previous;
        for (unsigned g=0;g<p.G;++g) accumulator[g]+=weight*seed.rows[uint64_t(location)*p.G+g];
        previous=level;
      }
      require(previous==p.normalizer,"threshold weights do not sum to one");
      unsigned factor=p.normalizer/p.scale;
      for (unsigned g=0;g<p.G;++g) {
        require(!(accumulator[g]%factor),"nonintegral numerator at declared clearing scale");
        unsigned value=accumulator[g]/factor;
        require(value<=p.scale*p.beta[g],"reconstructed output count outside bounds");
        out[g]=value;
      }
    }
    for (unsigned g=0;g<p.G;++g) {
      if (divisor>1) divisor=std::gcd(divisor,unsigned(out[g]));
    }
  }
  result.minimal_scale=p.scale/divisor;
  return result;
}
static uint64_t audit_reconstructed(const Geometry& p,const std::vector<uint16_t>& table) {
  for (uint32_t vertex=0;vertex<p.N;++vertex) for (unsigned g=0;g<p.G;++g)
    require(table[uint64_t(vertex)*p.G+g]<=p.scale*p.beta[g],"independent output bound violation");
  for (unsigned atom=0;atom<p.boundary.size();++atom) for (unsigned g=0;g<p.G;++g)
    require(table[uint64_t(p.boundary[atom])*p.G+g]==((p.rhs[g]&(1u<<atom))?p.scale*p.beta[g]:0),"reconstructed occurrence mismatch");
  uint64_t edges=0;
  for (unsigned axis=0;axis<p.L;++axis) {
    uint32_t side=1u<<axis; unsigned budget=p.alpha[axis]*p.scale;
    for (uint32_t block=0;block<p.N;block+=2*side)
      for (uint32_t vertex=block;vertex<block+side;++vertex) {
        const uint16_t* left=p.G?table.data()+uint64_t(vertex)*p.G:nullptr;
        const uint16_t* right=p.G?table.data()+uint64_t(vertex+side)*p.G:nullptr;
        unsigned distance=0;
        for (unsigned g=0;g<p.G;++g) {
          int a=left[g],b=right[g]; distance+=unsigned(a>b?a-b:b-a);
        }
        require(distance<=budget,"reconstructed full cube edge violation");
        ++edges;
      }
  }
  require(edges==uint64_t(p.L)*(p.N/2),"incomplete reconstructed edge coverage");
  return edges;
}
static void reply(const std::string& json,const std::vector<unsigned char>& seed,
                  const std::vector<uint16_t>& queries) {
  put_number(json.size(),4); put_number(seed.size(),4); put_number(queries.size()*2,4);
  std::cout.write(json.data(),json.size());
  if (!seed.empty()) std::cout.write(reinterpret_cast<const char*>(seed.data()),seed.size());
  for (uint16_t value:queries) put_number(value,2);
  std::cout.flush();
}
int main() {
  std::ios::sync_with_stdio(false); std::cin.tie(nullptr);
  try {
    while (std::cin.peek()!=EOF) {
      auto start=Clock::now(); char magic[8];
      require(bool(std::cin.read(magic,8)) && std::string(magic,8)=="HECPRF01","invalid request magic");
      unsigned id=number(4), n=number(4), dimensions=number(4);
      uint64_t raw_bytes=number(8); unsigned seed_count=number(4); uint64_t declared_scale=number(8);
      require(dimensions<=63 && raw_bytes<=4*1024*1024,"unsafe request size");
      std::vector<int32_t> coefficients(dimensions);
      for (auto& value:coefficients) { uint32_t bits=number(4); std::memcpy(&value,&bits,4); }
      Geometry p=geometry(n,coefficients);
      require(declared_scale==p.scale,"incorrect clearing scale");
      auto vertices=domain_recursive(p);
      require(vertices.size()==seed_count,"seed does not cover the complete compatible domain");
      require(raw_bytes==(uint64_t(seed_count)*p.row_bits+7)/8,"seed byte length differs from exact geometry");
      std::vector<unsigned char> payload(raw_bytes);
      require(!raw_bytes || bool(std::cin.read(reinterpret_cast<char*>(payload.data()),raw_bytes)),"truncated seed payload");
      auto seed=audit_seed(p,payload,vertices);
      auto result=reconstruct(p,seed);
      uint64_t reconstructed_edges=audit_reconstructed(p,result.rows);
      uint64_t micros=std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-start).count();
      std::ostringstream json;
      json<<"{\"ok\":true,\"index\":"<<id<<",\"n\":"<<n<<",\"L\":"<<p.L<<",\"G\":"<<p.G
          <<",\"R\":"<<p.R<<",\"source_vertices\":"<<p.N<<",\"seed_vertices\":"<<vertices.size()
          <<",\"seed_edges\":"<<seed.edges<<",\"checked_edges\":"<<reconstructed_edges
          <<",\"checked_vertices\":"<<p.N<<",\"clearing_scale\":"<<p.scale
          <<",\"scope\":\"original-cube-all-edges\",\"native_microseconds\":"<<micros<<"}";
      reply(json.str(),{},{});
    }
    return 0;
  } catch (const std::exception& error) {
    std::string message=error.what();
    for (char& c:message) if (c=='"' || c=='\\' || c<' ') c='?';
    reply("{\"ok\":false,\"error\":\""+message+"\"}",{},{});
    return 2;
  }
}
