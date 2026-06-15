# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Cython-compiled SAT model builder for the Q_L contraction-map problem."""

import numpy as np
cimport numpy as cnp
cimport cython


@cython.boundscheck(False)
@cython.wraparound(False)
def build_clauses(cnp.int8_t[:, ::1] val,
                  cnp.int8_t[:, ::1] fixed,
                  cnp.int32_t[::1] fix_count,
                  int L, int R,
                  cnp.int64_t[::1] alpha_np):
    """Build Q_L SAT model components in C-speed."""
    cdef int n_v = 1 << L
    cdef cnp.int64_t[:, ::1] var_id = np.zeros((n_v, R), dtype=np.int64)
    cdef int next_id = 0
    cdef int v, r, l, vp, fv, fw, cv
    cdef int bound, fixed_disagree, k_card
    cdef int top_id, d_id

    # Merge variables forced equal by saturated edges before assigning SAT IDs.
    cdef int n_cells = n_v * R
    cdef cnp.int32_t[::1] uf = np.empty(n_cells, dtype=np.int32)
    cdef int ci, ra, rb, A
    for ci in range(n_cells):
        uf[ci] = ci
    for v in range(n_v):
        for l in range(L):
            vp = v ^ (1 << l)
            if v >= vp:
                continue
            bound = <int>alpha_np[l]
            A = 0
            for r in range(R):
                if fixed[v, r] and fixed[vp, r] and val[v, r] != val[vp, r]:
                    A += 1
            if A != bound:
                continue
            for r in range(R):
                if fixed[v, r] == 0 and fixed[vp, r] == 0:
                    ra = v * R + r
                    while uf[ra] != ra:
                        uf[ra] = uf[uf[ra]]
                        ra = uf[ra]
                    rb = vp * R + r
                    while uf[rb] != rb:
                        uf[rb] = uf[uf[rb]]
                        rb = uf[rb]
                    if ra != rb:
                        if ra < rb:
                            uf[rb] = ra
                        else:
                            uf[ra] = rb

    cdef cnp.int32_t[::1] rep_to_id = np.zeros(n_cells, dtype=np.int32)
    for v in range(n_v):
        for r in range(R):
            if fixed[v, r] == 0:
                ci = v * R + r
                while uf[ci] != ci:
                    uf[ci] = uf[uf[ci]]
                    ci = uf[ci]
                if rep_to_id[ci] == 0:
                    next_id += 1
                    rep_to_id[ci] = next_id
                var_id[v, r] = rep_to_id[ci]
    cdef int n_vars = next_id

    cdef int max_aux_clauses = 4 * n_v * L // 2 * R + 100
    cdef cnp.int64_t[:, ::1] xor_clauses = np.empty((max_aux_clauses, 3), dtype=np.int64)
    cdef int n_xor_cl = 0

    # Row-equivalence symmetry breaking.
    cdef cnp.int64_t[::1] row_hash = np.zeros(R, dtype=np.int64)
    cdef cnp.int64_t H, MOD
    MOD = (<cnp.int64_t>1 << 62) - 57
    cdef int t
    for r in range(R):
        H = 0
        for v in range(n_v):
            t = 2
            if fixed[v, r]:
                t = val[v, r]
            H = (H * 3 + t + 1) % MOD
        row_hash[r] = H

    cdef cnp.int32_t[::1] row_group = np.empty(R, dtype=np.int32)
    for r in range(R):
        row_group[r] = r
    cdef int r1, r2
    cdef bint same
    for r1 in range(R):
        if row_group[r1] != r1:
            continue
        for r2 in range(r1 + 1, R):
            if row_group[r2] != r2 or row_hash[r1] != row_hash[r2]:
                continue
            same = True
            for v in range(n_v):
                if fixed[v, r1] != fixed[v, r2]:
                    same = False
                    break
                if fixed[v, r1] and val[v, r1] != val[v, r2]:
                    same = False
                    break
            if same:
                row_group[r2] = r1

    cdef int max_sym_clauses = R + 1
    cdef cnp.int64_t[:, ::1] sym_clauses = np.empty((max_sym_clauses, 2), dtype=np.int64)
    cdef int n_sym_cl = 0
    cdef int prev_r, sym_vid_prev, sym_vid_curr, v_probe
    for r1 in range(R):
        if row_group[r1] != r1:
            continue
        v_probe = -1
        for v in range(n_v):
            if fixed[v, r1] == 0:
                v_probe = v
                break
        if v_probe < 0:
            continue
        prev_r = r1
        for r2 in range(r1 + 1, R):
            if row_group[r2] != r1:
                continue
            sym_vid_prev = <int>var_id[v_probe, prev_r]
            sym_vid_curr = <int>var_id[v_probe, r2]
            if sym_vid_prev == 0 or sym_vid_curr == 0:
                prev_r = r2
                continue
            if sym_vid_prev == sym_vid_curr:
                prev_r = r2
                continue
            sym_clauses[n_sym_cl, 0] = -sym_vid_prev
            sym_clauses[n_sym_cl, 1] = sym_vid_curr
            n_sym_cl += 1
            prev_r = r2

    top_id = n_vars

    cdef int max_edges = n_v * L // 2 + 10
    cdef int max_diffs_total = max_edges * R + 10
    cdef cnp.int64_t[::1] diffs_flat = np.empty(max_diffs_total, dtype=np.int64)
    cdef cnp.int32_t[::1] edge_offsets = np.empty(max_edges + 1, dtype=np.int32)
    cdef cnp.int32_t[::1] k_card_arr = np.empty(max_edges, dtype=np.int32)
    cdef int n_edges = 0
    cdef int n_diffs_total = 0
    edge_offsets[0] = 0

    cdef int vid, vpid, edge_start, xor_start, top_id_start

    for v in range(n_v):
        for l in range(L):
            vp = v ^ (1 << l)
            if v >= vp:
                continue
            bound = <int>alpha_np[l]
            fixed_disagree = 0
            edge_start = n_diffs_total
            xor_start = n_xor_cl
            top_id_start = top_id
            for r in range(R):
                fv = fixed[v, r]
                fw = fixed[vp, r]
                if fv and fw:
                    if val[v, r] != val[vp, r]:
                        fixed_disagree += 1
                    continue
                if fv:
                    cv = val[v, r]
                    vpid = var_id[vp, r]
                    diffs_flat[n_diffs_total] = vpid if cv == 0 else -vpid
                    n_diffs_total += 1
                elif fw:
                    cv = val[vp, r]
                    vid = var_id[v, r]
                    diffs_flat[n_diffs_total] = vid if cv == 0 else -vid
                    n_diffs_total += 1
                else:
                    vid = var_id[v, r]
                    vpid = var_id[vp, r]
                    if vid == vpid:
                        continue
                    top_id += 1
                    d_id = top_id
                    xor_clauses[n_xor_cl, 0] = d_id
                    xor_clauses[n_xor_cl, 1] = -vid
                    xor_clauses[n_xor_cl, 2] = vpid
                    n_xor_cl += 1
                    xor_clauses[n_xor_cl, 0] = d_id
                    xor_clauses[n_xor_cl, 1] = vid
                    xor_clauses[n_xor_cl, 2] = -vpid
                    n_xor_cl += 1
                    diffs_flat[n_diffs_total] = d_id
                    n_diffs_total += 1
            if fixed_disagree > bound:
                return (np.asarray(var_id), top_id,
                        np.asarray(xor_clauses[:n_xor_cl]),
                        np.asarray(diffs_flat[:n_diffs_total]),
                        np.asarray(edge_offsets[:n_edges + 1]),
                        np.asarray(k_card_arr[:n_edges]),
                        np.asarray(sym_clauses[:n_sym_cl]),
                        False)
            if n_diffs_total == edge_start:
                continue
            k_card = bound - fixed_disagree
            if k_card < 0:
                return (np.asarray(var_id), top_id,
                        np.asarray(xor_clauses[:n_xor_cl]),
                        np.asarray(diffs_flat[:n_diffs_total]),
                        np.asarray(edge_offsets[:n_edges + 1]),
                        np.asarray(k_card_arr[:n_edges]),
                        np.asarray(sym_clauses[:n_sym_cl]),
                        False)
            if k_card >= n_diffs_total - edge_start:
                n_diffs_total = edge_start
                n_xor_cl = xor_start
                top_id = top_id_start
                continue
            edge_offsets[n_edges + 1] = n_diffs_total
            k_card_arr[n_edges] = k_card
            n_edges += 1

    return (np.asarray(var_id), top_id,
            np.asarray(xor_clauses[:n_xor_cl]),
            np.asarray(diffs_flat[:n_diffs_total]),
            np.asarray(edge_offsets[:n_edges + 1]),
            np.asarray(k_card_arr[:n_edges]),
            np.asarray(sym_clauses[:n_sym_cl]),
            True)
