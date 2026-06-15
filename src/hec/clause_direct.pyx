# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True, initializedcheck=False, nonecheck=False, overflowcheck=False
"""Direct kissat_add dispatch via C function pointers."""

import numpy as np
cimport numpy as cnp
cimport cython
from libc.stdint cimport intptr_t


ctypedef int (*kissat_add_fn_t)(void *, int) noexcept nogil
ctypedef int (*kissat_value_fn_t)(void *, int) noexcept nogil
cdef kissat_add_fn_t _kissat_add = NULL
cdef kissat_value_fn_t _kissat_value = NULL


def set_kissat_add_fn(intptr_t addr):
    global _kissat_add
    _kissat_add = <kissat_add_fn_t><void*>addr


def set_kissat_value_fn(intptr_t addr):
    global _kissat_value
    _kissat_value = <kissat_value_fn_t><void*>addr


@cython.boundscheck(False)
@cython.wraparound(False)
def get_model_direct(intptr_t kissat_ptr, int max_var,
                      cnp.int8_t[::1] out_buf):
    """Fill out_buf[v] with 1 if var v is True, 0 if False, indexed by var."""
    cdef void *solver = <void*>kissat_ptr
    cdef int v, val
    out_buf[0] = 0
    for v in range(1, max_var + 1):
        val = _kissat_value(solver, v)
        out_buf[v] = 1 if val > 0 else 0
    return max_var + 1


@cython.boundscheck(False)
@cython.wraparound(False)
def dispatch_xor_direct(intptr_t kissat_ptr,
                        cnp.int64_t[:, ::1] xor_clauses,
                        int n_xor):
    """Emit ternary clauses directly via kissat_add."""
    cdef void *solver = <void*>kissat_ptr
    cdef int i
    cdef kissat_add_fn_t add = _kissat_add
    with nogil:
        for i in range(n_xor):
            add(solver, <int>xor_clauses[i, 0])
            add(solver, <int>xor_clauses[i, 1])
            add(solver, <int>xor_clauses[i, 2])
            add(solver, 0)


@cython.boundscheck(False)
@cython.wraparound(False)
cdef int _dispatch_card_direct_nogil(void *solver,
                                     kissat_add_fn_t add,
                                     cnp.int64_t[::1] diffs_flat,
                                     cnp.int32_t[::1] edge_offsets,
                                     cnp.int32_t[::1] k_card_arr,
                                     int cur_top) noexcept nogil:
    """Emit sequential-counter at-most constraints directly via kissat_add."""
    cdef int n_edges = k_card_arr.shape[0]
    cdef int e, k_card, edge_start, edge_end, n_diffs, i, s0, s1_0, s2_0
    cdef int s_prev, s_i, d_i, s1_prev, s1_i, s2_prev, s2_i
    cdef cnp.int64_t d0, dlast
    cdef int k_card_val, sk_base, j, j_max
    cdef int s_i_1, s_im1_1, s_i_j, s_im1_j, s_im1_jm1, s_im1_k
    for e in range(n_edges):
        edge_start = edge_offsets[e]
        edge_end = edge_offsets[e + 1]
        n_diffs = edge_end - edge_start
        k_card = k_card_arr[e]
        if k_card >= n_diffs:
            continue
        if k_card == 0:
            for i in range(edge_start, edge_end):
                add(solver, <int>(-diffs_flat[i]))
                add(solver, 0)
        elif k_card == 1 and n_diffs >= 2:
            s0 = cur_top + 1
            cur_top += n_diffs - 1
            d0 = diffs_flat[edge_start]
            add(solver, <int>(-d0))
            add(solver, s0)
            add(solver, 0)
            for i in range(1, n_diffs - 1):
                s_prev = s0 + i - 1
                s_i = s0 + i
                d_i = <int>diffs_flat[edge_start + i]
                add(solver, -s_prev)
                add(solver, s_i)
                add(solver, 0)
                add(solver, -d_i)
                add(solver, s_i)
                add(solver, 0)
                add(solver, -d_i)
                add(solver, -s_prev)
                add(solver, 0)
            dlast = diffs_flat[edge_end - 1]
            add(solver, <int>(-dlast))
            add(solver, -(s0 + n_diffs - 2))
            add(solver, 0)
        elif k_card == 2 and n_diffs >= 3:
            s1_0 = cur_top + 1
            s2_0 = cur_top + n_diffs
            cur_top += 2 * (n_diffs - 1)
            d0 = diffs_flat[edge_start]
            add(solver, <int>(-d0))
            add(solver, s1_0)
            add(solver, 0)
            for i in range(1, n_diffs - 1):
                s1_prev = s1_0 + i - 1
                s1_i = s1_0 + i
                s2_prev = s2_0 + i - 1
                s2_i = s2_0 + i
                d_i = <int>diffs_flat[edge_start + i]
                add(solver, -d_i)
                add(solver, s1_i)
                add(solver, 0)
                add(solver, -s1_prev)
                add(solver, s1_i)
                add(solver, 0)
                add(solver, -d_i)
                add(solver, -s1_prev)
                add(solver, s2_i)
                add(solver, 0)
                add(solver, -s2_prev)
                add(solver, s2_i)
                add(solver, 0)
                add(solver, -d_i)
                add(solver, -s2_prev)
                add(solver, 0)
            dlast = diffs_flat[edge_end - 1]
            add(solver, <int>(-dlast))
            add(solver, -(s2_0 + n_diffs - 2))
            add(solver, 0)
        else:
            k_card_val = k_card
            sk_base = cur_top
            cur_top += k_card_val * (n_diffs - 1)
            d0 = diffs_flat[edge_start]
            add(solver, <int>(-d0))
            add(solver, sk_base + 1)
            add(solver, 0)
            for i in range(1, n_diffs - 1):
                d_i = <int>diffs_flat[edge_start + i]
                s_i_1 = sk_base + i * k_card_val + 1
                s_im1_1 = sk_base + (i - 1) * k_card_val + 1
                add(solver, -d_i)
                add(solver, s_i_1)
                add(solver, 0)
                add(solver, -s_im1_1)
                add(solver, s_i_1)
                add(solver, 0)
                j_max = i + 1 if (i + 1) < k_card_val else k_card_val
                for j in range(2, j_max + 1):
                    s_i_j = sk_base + i * k_card_val + j
                    s_im1_j = sk_base + (i - 1) * k_card_val + j
                    s_im1_jm1 = sk_base + (i - 1) * k_card_val + (j - 1)
                    add(solver, -d_i)
                    add(solver, -s_im1_jm1)
                    add(solver, s_i_j)
                    add(solver, 0)
                    if i >= j:
                        add(solver, -s_im1_j)
                        add(solver, s_i_j)
                        add(solver, 0)
                if i >= k_card_val:
                    s_im1_k = sk_base + (i - 1) * k_card_val + k_card_val
                    add(solver, -d_i)
                    add(solver, -s_im1_k)
                    add(solver, 0)
            dlast = diffs_flat[edge_end - 1]
            add(solver, <int>(-dlast))
            add(solver, -(sk_base + (n_diffs - 2) * k_card_val + k_card_val))
            add(solver, 0)
    return cur_top


@cython.boundscheck(False)
@cython.wraparound(False)
def dispatch_card_direct(intptr_t kissat_ptr,
                         cnp.int64_t[::1] diffs_flat,
                         cnp.int32_t[::1] edge_offsets,
                         cnp.int32_t[::1] k_card_arr,
                         int cur_top):
    """Python-callable wrapper that releases the GIL for the dispatch loop."""
    cdef void *solver = <void*>kissat_ptr
    cdef kissat_add_fn_t add = _kissat_add
    cdef int result
    with nogil:
        result = _dispatch_card_direct_nogil(
            solver, add, diffs_flat, edge_offsets, k_card_arr, cur_top)
    return result
