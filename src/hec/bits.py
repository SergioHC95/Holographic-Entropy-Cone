"""Bitstring helpers for contraction maps."""

from __future__ import annotations

from collections.abc import Sequence

BitPoint = tuple[int, ...]


def encode_bits(bits: Sequence[int]) -> str:
    return "".join(str(int(bit)) for bit in bits)


def d_alpha(left: Sequence[int], right: Sequence[int], alpha: Sequence[int]) -> int:
    return int(sum(weight for a, b, weight in zip(left, right, alpha, strict=True) if int(a) != int(b)))


def d_hamming(left: Sequence[int], right: Sequence[int]) -> int:
    return int(sum(1 for a, b in zip(left, right, strict=True) if int(a) != int(b)))


def bit_tuple(mask: int, width: int) -> BitPoint:
    return tuple((mask >> bit) & 1 for bit in range(width))


def bit_mask(bits: Sequence[int]) -> int:
    mask = 0
    for bit, value in enumerate(bits):
        if int(value):
            mask |= 1 << bit
    return mask


def enumerate_cube(width: int) -> list[BitPoint]:
    return [bit_tuple(mask, width) for mask in range(1 << width)]
