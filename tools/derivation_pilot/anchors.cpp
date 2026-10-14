// Reuse the frozen interval-closure kernel without changing its v2 semantics.
// This offline wrapper adds explicit fixed anchors and returns failed-run
// interval diagnostics to the extractor. A decoder needs only the saved pins.
#define HEC_CLOSURE_LIBRARY
#include "closure.cpp"

int main(int argc,char** argv) {
  try {
    unsigned limit=32,enumeration=64;std::string policy="lower";
    for (int i=1;i<argc;++i) {
      std::string flag=argv[i];
      if (flag=="--anchors" && i+1<argc) limit=std::stoul(argv[++i]);
      else if (flag=="--enumeration" && i+1<argc) enumeration=std::stoul(argv[++i]);
      else if (flag=="--policy" && i+1<argc) policy=argv[++i];
      else throw std::runtime_error("unknown anchored option");
    }
    need(limit<=128 && enumeration<=1024 && (policy=="lower" || policy=="upper"),"invalid anchored settings");
    std::string magic(8,'\0');need(bool(std::cin.read(magic.data(),8)) && magic=="HECPIN01","invalid anchored magic");
    unsigned n=get(4),dimension=get(4),declared=get(4);
    need(n>=1 && n<=6 && dimension==(1u<<n)-1,"invalid coefficient dimensions");
    std::vector<int32_t> normal(dimension);for (auto& x:normal) x=int32_t(get(4));
    Problem p(n,normal);need(declared==p.vertices.size(),"incomplete compatible domain");
    unsigned pins=get(4);need(pins<=64,"fixed-anchor safety cap");
    unsigned previous=0;
    for (unsigned i=0;i<pins;++i) {
      unsigned vertex=get(4);need(vertex<p.N && p.position[vertex]>=0 && (!i || vertex>previous),"noncanonical fixed anchors");
      previous=vertex;unsigned u=p.position[vertex];std::vector<unsigned> values;
      for (unsigned g=0;g<p.G;++g) { unsigned x=get(2);need(x<=p.beta[g],"fixed anchor outside count bounds");values.push_back(x); }
      for (const auto& [v,known]:p.boundary) need(v!=u || known==values,"fixed anchor contradicts occurrence");
      p.boundary.emplace_back(u,values);
    }
    need(std::cin.peek()==EOF,"trailing anchored request bytes");
    std::sort(p.boundary.begin(),p.boundary.end());p.boundary.erase(std::unique(p.boundary.begin(),p.boundary.end()),p.boundary.end());
    auto start=Clock::now();Engine engine(p,limit,enumeration,true,{});
    try {
      engine.run([&](unsigned,unsigned width,unsigned,unsigned){return policy=="lower"?0u:width;});
    } catch (const std::exception& error) {
      std::ostringstream failed;
      failed<<"{\"ok\":false,\"error\":\""<<error.what()<<"\",\"vertices\":"<<declared
            <<",\"groups\":"<<p.G<<",\"choices_before_failure\":"<<engine.tape.size()<<"}";
      // Binary arrays here are failed-attempt diagnostics, NOT proof rows.
      response(failed.str(),engine.low,engine.high,{});return 0;
    }
    std::ostringstream result;
    result<<"{\"ok\":true,\"vertices\":"<<declared<<",\"groups\":"<<p.G
          <<",\"pins\":"<<pins<<",\"choices\":"<<engine.tape.size()<<",\"initial_forced_cells\":"<<engine.initial_fixed
          <<",\"cells\":"<<engine.low.size()<<",\"anchors\":"<<engine.anchors.size()
          <<",\"native_microseconds\":"<<std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-start).count()<<"}";
    response(result.str(),engine.tape,engine.widths,engine.low);
  } catch (const std::exception& error) {
    response("{\"ok\":false,\"error\":\""+std::string(error.what())+"\"}");
  }
}
