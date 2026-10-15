// Exact implementation of simplify.smooth, not mathematical acceptance.
// All counts/denominators are uint64; coupled sums and products use uint128.
// No floating point, changed heuristic, relaxed work charge, or cube sampling.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <map>
#include <numeric>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

using U = uint64_t;
using W = unsigned __int128;
static constexpr U MAX_U = std::numeric_limits<U>::max();

static bool little_endian() {
    const uint32_t one = 1;
    return *reinterpret_cast<const unsigned char*>(&one) == 1;
}
template<class T> static std::vector<T> read_values(size_t count) {
    std::vector<T> result(count);
    if (count && !std::cin.read(reinterpret_cast<char*>(result.data()), std::streamsize(count * sizeof(T))))
        throw std::runtime_error("truncated request");
    if (!little_endian()) for (auto& value : result) {
        auto* bytes = reinterpret_cast<unsigned char*>(&value);
        std::reverse(bytes, bytes + sizeof(T));
    }
    return result;
}
template<class T> static T read_one() { return read_values<T>(1)[0]; }
template<class T> static void write_values(const std::vector<T>& values) {
    std::vector<T> swapped;
    const auto* output = &values;
    if (!little_endian()) {
        swapped = values;
        for (auto& value : swapped) {
            auto* bytes = reinterpret_cast<unsigned char*>(&value);
            std::reverse(bytes, bytes + sizeof(T));
        }
        output = &swapped;
    }
    if (!output->empty()) std::cout.write(reinterpret_cast<const char*>(output->data()), std::streamsize(output->size() * sizeof(T)));
}
static U distance(U a, U b) { return a >= b ? a - b : b - a; }
struct WorkLimit {};
struct Edge { uint32_t left, right; W budget, load; };
struct Request {
    uint32_t sequence, n, L, G, C, B, sweeps;
    U scale, max_work;
    std::vector<U> alpha, beta, rows, images;
    std::vector<uint32_t> vertices, fixed;
};
static Request read_request() {
    Request r;
    r.sequence = read_one<uint32_t>(); r.n = read_one<uint32_t>();
    r.L = read_one<uint32_t>(); r.G = read_one<uint32_t>();
    r.C = read_one<uint32_t>(); r.B = read_one<uint32_t>();
    r.scale = read_one<U>(); r.max_work = read_one<U>(); r.sweeps = read_one<uint32_t>();
    if (!r.n || r.n > 6 || r.L > 25 || r.G > 63 || !r.C || r.C > 1000000 ||
        W(r.C) * r.G > 16000000 || r.B > r.n + 1 || !r.scale || !r.max_work ||
        !r.sweeps || r.sweeps > 8) throw std::runtime_error("unsupported exact capability");
    r.alpha = read_values<U>(r.L); r.beta = read_values<U>(r.G);
    r.vertices = read_values<uint32_t>(r.C); r.fixed = read_values<uint32_t>(r.B);
    r.images = read_values<U>(size_t(r.B) * r.G); r.rows = read_values<U>(size_t(r.C) * r.G);
    for (U a : r.alpha) if (!a || a > 1024) throw std::runtime_error("invalid axis capacity");
    for (U b : r.beta) if (!b || b > 1024 || W(b) * r.scale > MAX_U)
        throw std::runtime_error("count exceeds exact uint64 capability");
    for (uint32_t i = 0; i < r.C; ++i) {
        if (r.vertices[i] >= (uint32_t(1) << r.L) || (i && r.vertices[i-1] >= r.vertices[i]))
            throw std::runtime_error("invalid ordered compatible vertices");
        for (uint32_t g = 0; g < r.G; ++g)
            if (W(r.rows[size_t(i)*r.G+g]) > W(r.beta[g]) * r.scale)
                throw std::runtime_error("source count bound violation");
    }
    for (uint32_t b = 0; b < r.B; ++b) {
        if (r.fixed[b] >= r.C) throw std::runtime_error("invalid boundary index");
        for (uint32_t g = 0; g < r.G; ++g)
            if (r.rows[size_t(r.fixed[b])*r.G+g] != r.images[size_t(b)*r.G+g])
                throw std::runtime_error("source occurrence boundary mismatch");
    }
    return r;
}
static void respond(uint32_t sequence, const std::string& meta, const std::vector<U>& rows) {
    write_values<uint32_t>({uint32_t(meta.size()), sequence});
    write_values<U>({U(rows.size()) * sizeof(U)});
    std::cout.write(meta.data(), std::streamsize(meta.size())); write_values<U>(rows); std::cout.flush();
    if (!std::cout) throw std::runtime_error("reply write failed");
}
static void smooth(const Request& r) {
    auto rows = r.rows;
    std::unordered_map<uint32_t, uint32_t> index;
    index.reserve(size_t(r.C) * 2);
    for (uint32_t u = 0; u < r.C; ++u) index.emplace(r.vertices[u], u);
    std::vector<Edge> edges;
    std::vector<std::vector<uint32_t>> adjacency(r.C);
    for (uint32_t u = 0; u < r.C; ++u) for (uint32_t axis = 0; axis < r.L; ++axis) {
        auto found = index.find(r.vertices[u] ^ (uint32_t(1) << axis));
        if (found == index.end() || found->second <= u) continue;
        uint32_t v = found->second;
        W load = 0, budget = W(r.alpha[axis]) * r.scale;
        for (uint32_t g = 0; g < r.G; ++g) load += distance(rows[size_t(u)*r.G+g], rows[size_t(v)*r.G+g]);
        if (load > budget) throw std::runtime_error("source compatible edge violation");
        uint32_t at = uint32_t(edges.size()); edges.push_back({u, v, budget, load});
        adjacency[u].push_back(at); adjacency[v].push_back(at);
    }
    std::vector<bool> fixed(r.C, false);
    for (uint32_t u : r.fixed) fixed[u] = true;
    std::set<U> denominators;
    for (U q = 1; q <= 256; ++q) if (r.scale % q == 0) denominators.insert(q);
    for (unsigned k = 0; k < 31; ++k) if (r.scale % (U(1) << k) == 0) denominators.insert(U(1) << k);
    U work = 0, moves = 0, visits = 0, actual_sweeps = 0;
    auto charge = [&](U amount) {
        if (amount > r.max_work - work) throw WorkLimit{};
        work += amount;
    };
    for (uint32_t sweep = 0; sweep < r.sweeps; ++sweep) {
        U before = moves; ++actual_sweeps;
        for (uint32_t g = 0; g < r.G; ++g) {
            std::vector<uint32_t> parent(r.C), component(r.C);
            std::iota(parent.begin(), parent.end(), 0);
            auto root = [&](uint32_t u) {
                while (parent[u] != u) { parent[u] = parent[parent[u]]; u = parent[u]; }
                return u;
            };
            for (const auto& edge : edges) {
                charge(1);
                if (edge.load == edge.budget && rows[size_t(edge.left)*r.G+g] == rows[size_t(edge.right)*r.G+g]) {
                    uint32_t a = root(edge.left), b = root(edge.right);
                    if (a < b) parent[b] = a; else if (b < a) parent[a] = b;
                }
            }
            std::vector<std::vector<uint32_t>> components(r.C);
            for (uint32_t u = 0; u < r.C; ++u) { component[u] = root(u); components[component[u]].push_back(u); }
            // The representative is the smallest member. Ascending roots and
            // ascending members exactly match Python's insertion-ordered dict.
            for (const auto& members : components) {
                if (members.empty()) continue;
                ++visits;
                if (std::any_of(members.begin(), members.end(), [&](uint32_t u) { return fixed[u]; })) continue;
                U old = rows[size_t(members[0])*r.G+g], low = 0, high = U(W(r.beta[g]) * r.scale);
                std::map<U, U> neighbors;
                std::vector<std::pair<uint32_t, U>> crossing;
                for (uint32_t u : members) {
                    if (rows[size_t(u)*r.G+g] != old) throw std::runtime_error("nonconstant tight component");
                    for (uint32_t at : adjacency[u]) {
                        charge(1); const auto& edge = edges[at];
                        uint32_t v = edge.left == u ? edge.right : edge.left;
                        if (component[v] == component[u]) continue;
                        U value = rows[size_t(v)*r.G+g], previous = distance(old, value);
                        if (edge.load < previous || edge.load - previous > edge.budget)
                            throw std::runtime_error("negative coupled residual budget");
                        W residual = edge.budget - (edge.load - previous);
                        low = std::max(low, residual > value ? U(0) : U(W(value) - residual));
                        high = U(std::min(W(high), W(value) + residual));
                        ++neighbors[value]; crossing.emplace_back(at, value);
                    }
                }
                if (!(low <= old && old <= high)) throw std::runtime_error("feasible interval excluded source");
                std::set<U> choices{old, low, high};
                for (const auto& neighbor : neighbors) if (low <= neighbor.first && neighbor.first <= high)
                    choices.insert(neighbor.first);
                for (U denominator : denominators) {
                    U step = r.scale / denominator;
                    W first = ((W(low) + step - 1) / step) * step, last = (high / step) * step;
                    if (first > last) continue;
                    choices.insert(U(first)); choices.insert(U(last));
                    choices.insert(U(std::min(last, std::max(first, W((old / step) * step)))));
                    W upper = ((W(old) + step - 1) / step) * step;
                    if (first <= upper && upper <= last) choices.insert(U(upper));
                }
                using Score = std::tuple<U, U, W, U>;
                Score best; bool selected = false; U value = old;
                for (U candidate : choices) {
                    charge(U(neighbors.size()) + 1);
                    U discontinuities = 0; W variation = 0;
                    for (const auto& neighbor : neighbors) {
                        if (neighbor.first != candidate) discontinuities += neighbor.second;
                        variation += W(neighbor.second) * distance(candidate, neighbor.first);
                    }
                    Score score{r.scale / std::gcd(r.scale, candidate), discontinuities, variation, candidate};
                    if (!selected || score < best) { selected = true; best = score; value = candidate; }
                }
                if (value == old) continue;
                for (const auto& item : crossing) {
                    auto& edge = edges[item.first];
                    U a = distance(value, item.second), b = distance(old, item.second);
                    if (a >= b) edge.load += a - b; else edge.load -= b - a;
                    if (edge.load > edge.budget) throw std::runtime_error("component move violated coupled edge");
                }
                for (uint32_t u : members) rows[size_t(u)*r.G+g] = value;
                ++moves;
            }
        }
        if (before == moves) break;
    }
    U divisor = r.scale;
    for (U value : rows) divisor = std::gcd(divisor, value);
    U new_scale = r.scale / divisor, changes = 0;
    for (const auto& edge : edges) {
        W load = 0;
        for (uint32_t g = 0; g < r.G; ++g) load += distance(rows[size_t(edge.left)*r.G+g], rows[size_t(edge.right)*r.G+g]);
        if (load != edge.load || load > edge.budget) throw std::runtime_error("final exact edge audit failed");
    }
    for (uint32_t b = 0; b < r.B; ++b) for (uint32_t g = 0; g < r.G; ++g)
        if (rows[size_t(r.fixed[b])*r.G+g] != r.images[size_t(b)*r.G+g])
            throw std::runtime_error("synthesis changed occurrence boundary");
    for (size_t i = 0; i < rows.size(); ++i) {
        rows[i] /= divisor;
        if (W(r.rows[i]) * new_scale != W(rows[i]) * r.scale) ++changes;
    }
    std::ostringstream meta;
    meta << "{\"ok\":true,\"method\":\"exact-tight-component-smoothing/experimental-1\","
         << "\"status\":\"complete_compatible_seed_pending_independent_full_cube_acceptance\","
         << "\"source_scale\":\"" << r.scale << "\",\"candidate_scale\":\"" << new_scale << "\","
         << "\"changed_cells\":" << changes << ",\"component_moves\":" << moves
         << ",\"component_visits\":" << visits << ",\"compatible_edges\":" << edges.size()
         << ",\"sweeps\":" << actual_sweeps << ",\"work\":" << work
         << ",\"strict_description_improvement\":\"not_yet_measured\"}";
    respond(r.sequence, meta.str(), rows);
}
int main() {
    std::ios::sync_with_stdio(false); std::cin.tie(nullptr);
    try {
        while (true) {
            char magic[8]; std::cin.read(magic, 8);
            if (std::cin.gcount() == 0 && std::cin.eof()) return 0;
            if (std::cin.gcount() != 8 || std::memcmp(magic, "HECSMO01", 8)) throw std::runtime_error("invalid request version");
            Request request = read_request();
            try { smooth(request); }
            catch (const WorkLimit&) { respond(request.sequence, "{\"ok\":false,\"status\":\"work_limit\"}", {}); }
        }
    } catch (const std::exception& error) {
        std::cerr << "exact smoothing failed: " << error.what() << '\n'; return 1;
    }
}
