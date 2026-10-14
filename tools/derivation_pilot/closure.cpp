// Offline integer-compatible-seed derivation experiment. Not a production
// solver or an accepted repository proof format. Every result is subsequently
// checked by the independent original-cube verifier.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <deque>
#include <functional>
#include <iostream>
#include <numeric>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

using Clock = std::chrono::steady_clock;
static void need(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}
static uint64_t get(unsigned bytes) {
  unsigned char data[8]{};
  need(bytes<=8 && bool(std::cin.read(reinterpret_cast<char*>(data),bytes)),"truncated request");
  uint64_t value=0;
  for (unsigned i=0;i<bytes;++i) value|=uint64_t(data[i])<<(8*i);
  return value;
}
static void put(uint64_t value,unsigned bytes) {
  for (unsigned i=0;i<bytes;++i) std::cout.put(char(value>>(8*i)));
}
struct Problem {
  unsigned n,L,G,N;
  std::vector<unsigned> lhs,alpha,rhs,beta,metric,vertices;
  std::vector<int> position;
  std::vector<std::vector<std::pair<unsigned,unsigned>>> edges;
  std::vector<std::pair<unsigned,std::vector<unsigned>>> boundary;
  uint64_t edge_count=0,table_bits=0;
  Problem(unsigned parties,const std::vector<int32_t>& coefficients) {
    n=parties;
    need(n>=1 && n<=6 && coefficients.size()==(1u<<n)-1,"unsupported party dimension");
    std::vector<unsigned> supports;
    for (unsigned size=1;size<=n;++size) {
      std::function<void(unsigned,unsigned,unsigned)> visit=[&](unsigned first,unsigned left,unsigned mask) {
        if (!left) { supports.push_back(mask);return; }
        for (unsigned i=first;i+left<=n;++i) visit(i+1,left-1,mask|(1u<<i));
      };
      visit(0,size,0);
    }
    unsigned divisor=0;
    for (unsigned i=0;i<supports.size();++i) {
      int64_t a=coefficients[i];
      divisor=std::gcd(divisor,unsigned(a<0?-a:a));
      if (a>0) {
        need(a<=32,"unsupported source capacity");lhs.push_back(supports[i]);alpha.push_back(unsigned(a));
      } else if (a<0) {
        need(-a<=63,"unsupported RHS capacity");rhs.push_back(supports[i]);beta.push_back(unsigned(-a));
      }
    }
    need(divisor==0 || divisor==1,"nonprimitive inequality");
    L=lhs.size();G=rhs.size();
    need(L<=17 && std::accumulate(beta.begin(),beta.end(),0u)<=63,"unsupported native experiment dimensions");
    N=1u<<L;
    metric.assign(N,0);
    for (unsigned x=1;x<N;++x) {
      unsigned bit=unsigned(__builtin_ctz(x));metric[x]=metric[x&(x-1)]+alpha[bit];
    }
    std::vector<std::pair<unsigned,unsigned>> nested,disjoint;
    for (unsigned i=0;i<L;++i) for (unsigned j=0;j<L;++j) {
      if (i<j && !(lhs[i]&lhs[j])) disjoint.emplace_back(i,j);
      if (i!=j && (lhs[i]&lhs[j])==lhs[i]) nested.emplace_back(i,j);
    }
    position.assign(N,-1);
    for (unsigned x=0;x<N;++x) {
      bool compatible=true;
      for (auto [i,j]:disjoint) if ((x&(1u<<i)) && (x&(1u<<j))) { compatible=false;break; }
      if (compatible) for (auto [i,j]:nested)
        if ((x&(1u<<i)) && !(x&(1u<<j))) { compatible=false;break; }
      if (compatible) { position[x]=vertices.size();vertices.push_back(x); }
    }
    edges.resize(vertices.size());
    for (unsigned u=0;u<vertices.size();++u) for (unsigned i=0;i<L;++i) {
      int v=position[vertices[u]^(1u<<i)];
      if (v>=0) { edges[u].emplace_back(unsigned(v),alpha[i]);if (u<unsigned(v)) ++edge_count; }
    }
    for (unsigned atom=0;atom<=n;++atom) {
      unsigned x=0;std::vector<unsigned> values;
      for (unsigned i=0;i<L;++i) if (lhs[i]&(1u<<atom)) x|=1u<<i;
      for (unsigned g=0;g<G;++g) values.push_back(rhs[g]&(1u<<atom)?beta[g]:0);
      need(position[x]>=0,"boundary outside complete compatible domain");
      unsigned u=position[x];
      for (auto& saved:boundary) need(saved.first!=u || saved.second==values,"conflicting boundaries");
      boundary.emplace_back(u,values);
    }
    std::sort(boundary.begin(),boundary.end());boundary.erase(std::unique(boundary.begin(),boundary.end()),boundary.end());
    unsigned widths=0;
    for (unsigned cap:beta) { unsigned w=0;for (;cap;cap>>=1) ++w;widths+=w; }
    table_bits=uint64_t(vertices.size())*widths;
  }
};
struct PairBox { unsigned a,b;std::vector<unsigned> low,high; };
struct Pick {
  unsigned unknown,width,distance,vertex,row,generation;
  bool operator>(const Pick& other) const {
    return std::tie(unknown,width,distance,vertex,row,generation)>
           std::tie(other.unknown,other.width,other.distance,other.vertex,other.row,other.generation);
  }
};
class Engine {
 public:
  const Problem& p;
  std::vector<uint16_t> low,high,oracle,tape,widths;
  std::vector<unsigned> anchors,distance,generation;
  std::vector<unsigned char> queued,registered,candidate_dirty;
  std::vector<PairBox> boxes;
  std::deque<unsigned> queue;
  std::priority_queue<Pick,std::vector<Pick>,std::greater<Pick>> picks;
  unsigned anchor_limit,enumeration_limit,initial_fixed=0,boundary_fixed=0;
  uint64_t narrowed=0,edge_visits=0,ball_visits=0,pair_visits=0,choice_bits=0;
  uint64_t enumerated_rows=0,candidate_assignments=0;
  bool pair_rules;
  Engine(const Problem& problem,unsigned limit,unsigned enumeration,bool pairs,const std::vector<uint16_t>& target)
      :p(problem),oracle(target),anchor_limit(limit),enumeration_limit(enumeration),pair_rules(pairs) {
    unsigned count=p.vertices.size();
    low.assign(uint64_t(count)*p.G,0);high.resize(low.size());
    distance.assign(count,UINT32_MAX);generation.assign(count,0);
    queued.assign(count,0);registered.assign(count,0);candidate_dirty.assign(count,1);
    for (unsigned u=0;u<count;++u) {
      for (unsigned g=0;g<p.G;++g) high[uint64_t(u)*p.G+g]=p.beta[g];
      for (const auto& [v,_values]:p.boundary) distance[u]=std::min(distance[u],p.metric[p.vertices[u]^p.vertices[v]]);
    }
    if (!oracle.empty()) need(oracle.size()==low.size(),"oracle size mismatch");
    for (unsigned u=0;u<count;++u) for (unsigned g=0;g<p.G;++g)
      if (!oracle.empty()) need(oracle[uint64_t(u)*p.G+g]<=p.beta[g],"oracle outside count bounds");
    for (auto& [u,values]:p.boundary) for (unsigned g=0;g<p.G;++g) {
      unsigned k=u*p.G+g;low[k]=high[k]=values[g];
      if (!oracle.empty()) need(oracle[k]==values[g],"oracle boundary mismatch");
    }
    boundary_fixed=fixed();
    for (unsigned u=0;u<count;++u) refresh(u);
    for (auto& [u,_values]:p.boundary) add_anchor(u);
  }
  unsigned fixed() const {
    unsigned total=0;for (unsigned i=0;i<low.size();++i) total+=low[i]==high[i];return total;
  }
  Pick pick_for(unsigned u) const {
    unsigned unknown=0,width=0;
    for (unsigned g=0;g<p.G;++g) { unsigned i=u*p.G+g;unknown+=low[i]!=high[i];width+=high[i]-low[i]; }
    return {unknown,width,distance[u],p.vertices[u],u,generation[u]};
  }
  void enqueue(unsigned u) { if (!queued[u]) { queued[u]=1;queue.push_back(u); } }
  void rebuild_heap() {
    decltype(picks) fresh;
    for (unsigned u=0;u<p.vertices.size();++u) { auto k=pick_for(u);if (k.unknown) fresh.push(k); }
    picks.swap(fresh);
  }
  void refresh(unsigned u) {
    candidate_dirty[u]=1;
    for (auto [v,_budget]:p.edges[u]) candidate_dirty[v]=1;
    ++generation[u];enqueue(u);auto k=pick_for(u);if (k.unknown) picks.push(k);
    if (picks.size()>8*p.vertices.size()) rebuild_heap();
  }
  void narrow(unsigned u,unsigned g,int minimum,int maximum) {
    unsigned i=u*p.G+g;
    int lo=std::max(int(low[i]),minimum),hi=std::min(int(high[i]),maximum);
    need(lo<=hi,"inconsistent exact interval constraints");
    if (!oracle.empty()) need(lo<=oracle[i] && oracle[i]<=hi,"inference incorrectly excludes source seed");
    if (lo!=low[i] || hi!=high[i]) { low[i]=lo;high[i]=hi;++narrowed;refresh(u); }
  }
  void edge(unsigned u,unsigned v,unsigned budget) {
    ++edge_visits;
    unsigned total=0;unsigned minimum[63]{};
    for (unsigned g=0;g<p.G;++g) {
      unsigned a=u*p.G+g,b=v*p.G+g;
      minimum[g]=unsigned(std::max({0,int(low[a])-int(high[b]),int(low[b])-int(high[a])}));
      total+=minimum[g];
    }
    need(total<=budget,"partial coupled edge exceeds capacity");
    for (unsigned g=0;g<p.G;++g) {
      unsigned a=u*p.G+g,b=v*p.G+g;int slack=int(budget-total+minimum[g]);
      int al=low[a],ah=high[a],bl=low[b],bh=high[b];
      narrow(u,g,bl-slack,bh+slack);narrow(v,g,al-slack,ah+slack);
    }
  }
  template<class Lower,class Upper> void box(unsigned u,unsigned budget,Lower below,Upper above) {
    unsigned total=0,minimum[63]{};
    for (unsigned g=0;g<p.G;++g) {
      unsigned k=u*p.G+g;
      minimum[g]=unsigned(std::max({0,int(low[k])-int(above(g)),int(below(g))-int(high[k])}));
      total+=minimum[g];
    }
    need(total<=budget,"partial anchor interval exceeds distance budget");
    for (unsigned g=0;g<p.G;++g) {
      int slack=int(budget-total+minimum[g]);
      narrow(u,g,int(below(g))-slack,int(above(g))+slack);
    }
  }
  void add_anchor(unsigned u) {
    if (registered[u] || anchors.size()>=anchor_limit || pick_for(u).unknown) return;
    registered[u]=1;
    if (pair_rules) for (unsigned v:anchors) {
      unsigned input=p.metric[p.vertices[u]^p.vertices[v]],output=0;
      PairBox b{u,v,{},{}};
      for (unsigned g=0;g<p.G;++g) {
        unsigned x=low[u*p.G+g],y=low[v*p.G+g];output+=x>y?x-y:y-x;
        b.low.push_back(std::min(x,y));b.high.push_back(std::max(x,y));
      }
      need(output<=input,"fully fixed anchors violate contraction");
      // Integer seed values make a source-minus-image slack of 0 or 1
      // insufficient to leave the output coordinate interval by one unit.
      if (input-output<=1) boxes.push_back(std::move(b));
    }
    anchors.push_back(u);
    for (unsigned v=0;v<p.vertices.size();++v) { enqueue(v);candidate_dirty[v]=1; }
  }
  void enumerate_candidates(unsigned u) {
    candidate_dirty[u]=0;
    std::vector<unsigned> unknown;
    unsigned product=1;
    for (unsigned g=0;g<p.G;++g) {
      unsigned k=u*p.G+g,width=high[k]-low[k];
      if (width) {
        if (product>enumeration_limit/(width+1)) return;
        product*=width+1;unknown.push_back(g);
      }
    }
    if (unknown.empty()) return;
    ++enumerated_rows;
    struct Constraint { std::vector<int> lo,hi,minimum;int remaining; };
    std::vector<Constraint> constraints;
    auto add=[&](unsigned v,unsigned budget,bool anchor) {
      Constraint c{{},{},{},int(budget)};
      for (unsigned g=0;g<p.G;++g) {
        unsigned here=u*p.G+g,there=v*p.G+g;
        int a=low[there],b=anchor?a:high[there];
        int minimum=std::max({0,int(low[here])-b,a-int(high[here])});
        c.lo.push_back(a);c.hi.push_back(b);c.minimum.push_back(minimum);c.remaining-=minimum;
      }
      need(c.remaining>=0,"candidate constraint already inconsistent");constraints.push_back(std::move(c));
    };
    for (auto [v,budget]:p.edges[u]) add(v,budget,false);
    for (unsigned v:anchors) add(v,p.metric[p.vertices[u]^p.vertices[v]],true);
    std::vector<int> values(p.G),minima(p.G,INT32_MAX),maxima(p.G,-1);
    for (unsigned g=0;g<p.G;++g) values[g]=low[u*p.G+g];
    unsigned accepted=0;
    std::function<void(unsigned)> visit=[&](unsigned at) {
      if (at==unknown.size()) {
        ++accepted;++candidate_assignments;
        for (unsigned g:unknown) { minima[g]=std::min(minima[g],values[g]);maxima[g]=std::max(maxima[g],values[g]); }
        return;
      }
      unsigned g=unknown[at],k=u*p.G+g;
      for (int value=low[k];value<=high[k];++value) {
        values[g]=value;bool feasible=true;
        for (auto& c:constraints) {
          c.remaining-=std::max({0,c.lo[g]-value,value-c.hi[g]})-c.minimum[g];
          if (c.remaining<0) feasible=false;
        }
        if (feasible) visit(at+1);
        for (auto& c:constraints) c.remaining+=std::max({0,c.lo[g]-value,value-c.hi[g]})-c.minimum[g];
      }
    };
    visit(0);need(accepted>0,"empty exact candidate intersection");
    for (unsigned g:unknown) narrow(u,g,minima[g],maxima[g]);
  }
  void propagate() {
    while (true) {
    while (!queue.empty()) {
      unsigned u=queue.front();queue.pop_front();queued[u]=0;
      for (unsigned v:anchors) {
        ++ball_visits;
        box(u,p.metric[p.vertices[u]^p.vertices[v]],
            [&](unsigned g){return low[v*p.G+g];},[&](unsigned g){return low[v*p.G+g];});
      }
      for (const auto& b:boxes) {
        ++pair_visits;
        unsigned outside=(p.vertices[u]^p.vertices[b.a])&~(p.vertices[b.a]^p.vertices[b.b]);
        box(u,p.metric[outside],[&](unsigned g){return b.low[g];},[&](unsigned g){return b.high[g];});
      }
      for (auto [v,budget]:p.edges[u]) edge(u,v,budget);
      add_anchor(u);
    }
    if (enumeration_limit) for (unsigned u=0;u<p.vertices.size();++u)
      if (candidate_dirty[u]) enumerate_candidates(u);
    if (queue.empty()) break;
    }
  }
  std::pair<unsigned,unsigned> next() {
    while (!picks.empty()) {
      Pick k=picks.top();picks.pop();
      if (k.generation!=generation[k.row] || !k.unknown) continue;
      unsigned group=p.G,width=UINT32_MAX;
      for (unsigned g=0;g<p.G;++g) {
        unsigned d=high[k.row*p.G+g]-low[k.row*p.G+g];
        if (d && d<width) { group=g;width=d; }
      }
      need(group<p.G,"invalid deterministic next-choice state");return {k.row,group};
    }
    return {unsigned(p.vertices.size()),0};
  }
  void finish_check() const {
    need(fixed()==low.size(),"incomplete seed derivation");
    for (unsigned u=0;u<p.vertices.size();++u) for (auto [v,budget]:p.edges[u]) if (u<v) {
      unsigned delta=0;
      for (unsigned g=0;g<p.G;++g) { int a=low[u*p.G+g],b=low[v*p.G+g];delta+=unsigned(std::abs(a-b)); }
      need(delta<=budget,"derived compatible edge violation");
    }
    if (!oracle.empty()) need(low==oracle,"derivation changes source seed");
  }
  template<class Choice> void run(Choice choose) {
    propagate();initial_fixed=fixed();
    while (true) {
      auto [u,g]=next();if (u==p.vertices.size()) break;
      unsigned k=u*p.G+g,width=high[k]-low[k];
      unsigned offset=choose(unsigned(tape.size()),width,k,low[k]);
      need(offset<=width,"choice offset outside inferred interval");
      tape.push_back(offset);widths.push_back(width);
      unsigned bits=0;for (unsigned x=width;x;x>>=1) ++bits;choice_bits+=bits;
      narrow(u,g,low[k]+offset,low[k]+offset);propagate();
    }
    finish_check();
  }
};
static void response(const std::string& json,const std::vector<uint16_t>& tape={},
                     const std::vector<uint16_t>& widths={},const std::vector<uint16_t>& rows={}) {
  put(json.size(),4);put(tape.size()*2,4);put(widths.size()*2,4);put(rows.size()*2,4);
  std::cout<<json;
  for (auto value:tape) put(value,2);
  for (auto value:widths) put(value,2);
  for (auto value:rows) put(value,2);
}
#ifndef HEC_CLOSURE_LIBRARY
int main(int argc,char** argv) {
  std::string mode="";unsigned limit=32,enumeration=64;bool pairs=true;
  try {
    for (int i=1;i<argc;++i) {
      std::string flag=argv[i];
      if (flag=="--mode" && i+1<argc) mode=argv[++i];
      else if (flag=="--anchors" && i+1<argc) limit=std::stoul(argv[++i]);
      else if (flag=="--enumeration" && i+1<argc) enumeration=std::stoul(argv[++i]);
      else if (flag=="--no-pairs") pairs=false;
      else throw std::runtime_error("unknown experiment option");
    }
    need(mode=="encode" || mode=="decode" || mode=="lower" || mode=="upper","unknown derivation mode");
    need(limit<=128 && enumeration<=1024,"closure experiment safety cap");
    std::string magic(8,'\0');need(bool(std::cin.read(magic.data(),8)) && magic=="HECDRV01","invalid request magic");
    unsigned n=get(4),dimension=get(4),declared=get(4);
    need(n>=1 && n<=6 && dimension==(1u<<n)-1,"invalid coefficient dimensions");
    std::vector<int32_t> normal(dimension);
    for (auto& a:normal) a=int32_t(get(4));
    Problem p(n,normal);need(declared==p.vertices.size(),"declared compatible count mismatch");
    std::vector<uint16_t> oracle,choices;
    unsigned expected=0,layout=0,supplied=0;
    std::vector<std::pair<unsigned,unsigned>> exceptions;
    if (mode=="encode") {
      oracle.resize(uint64_t(declared)*p.G);for (auto& a:oracle) a=get(2);
    } else if (mode=="decode") {
      expected=get(4);layout=get(4);supplied=get(4);
      need(expected<=uint64_t(declared)*p.G && layout<=2 && supplied<=expected,"unsafe choice tape dimensions");
      if (!layout) {
        need(supplied==expected,"explicit tape count mismatch");choices.resize(supplied);for (auto& a:choices) a=get(2);
      } else {
        for (unsigned i=0;i<supplied;++i) {
          unsigned at=get(4),value=get(2);
          need(at<expected && (exceptions.empty() || at>exceptions.back().first),"noncanonical choice exceptions");
          exceptions.emplace_back(at,value);
        }
      }
    }
    need(std::cin.peek()==EOF,"trailing request bytes");
    auto started=Clock::now();Engine engine(p,limit,enumeration,pairs,oracle);unsigned used=0;
    engine.run([&](unsigned step,unsigned width,unsigned k,unsigned low) {
      if (mode=="encode") return unsigned(oracle[k]-low);
      if (mode=="lower") return 0u;
      if (mode=="upper") return width;
      need(step<expected,"missing choice tape entries");
      if (!layout) return unsigned(choices[step]);
      if (used<exceptions.size() && exceptions[used].first==step) return exceptions[used++].second;
      return layout==1?0u:width;
    });
    if (mode=="decode") need(engine.tape.size()==expected && used==exceptions.size(),"trailing choice tape entries");
    auto elapsed=std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-started).count();
    std::ostringstream json;
    json<<"{\"ok\":true,\"vertices\":"<<declared<<",\"groups\":"<<p.G
        <<",\"compatible_edges\":"<<p.edge_count<<",\"table_bits\":"<<p.table_bits
        <<",\"cells\":"<<engine.low.size()<<",\"boundary_fixed_cells\":"<<engine.boundary_fixed
        <<",\"initial_forced_cells\":"<<engine.initial_fixed<<",\"choices\":"<<engine.tape.size()
        <<",\"choice_bits\":"<<engine.choice_bits<<",\"anchors\":"<<engine.anchors.size()
        <<",\"pair_boxes\":"<<engine.boxes.size()<<",\"narrowing_steps\":"<<engine.narrowed
        <<",\"edge_visits\":"<<engine.edge_visits<<",\"ball_visits\":"<<engine.ball_visits
        <<",\"pair_visits\":"<<engine.pair_visits<<",\"native_microseconds\":"<<elapsed<<"}";
    std::string output=json.str();output.pop_back();
    output+=",\"enumerated_rows\":"+std::to_string(engine.enumerated_rows)
           +",\"candidate_assignments\":"+std::to_string(engine.candidate_assignments)+"}";
    response(output,engine.tape,engine.widths,engine.low);
  } catch (const std::exception& error) {
    std::string message=error.what();
    need(message.find_first_of("\"\\\n")==std::string::npos,"unsafe error message");
    response("{\"ok\":false,\"error\":\""+message+"\"}");
  }
}
#endif
