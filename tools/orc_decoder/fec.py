"""FEC decoders for the OrcXM chain.

Viterbi decoder for the rate-1/3 K=7 convolutional code, and
Berlekamp-Massey Reed-Solomon decoder for RS(255,223).
Inverts what xm_frame.py puts on the channel.
"""

import numpy as np


# ---------------------------------------------------------------------------
# Viterbi decoder: rate 1/3, K=7, polys 171/133/165 (octal)
# ---------------------------------------------------------------------------
_CONV_POLYS = (0o171, 0o133, 0o165)
_CONV_K = 7
_NSTATES = 1 << (_CONV_K - 1)


def _build_trellis():
    """Precompute next-state and output tables."""
    next_state = np.zeros((_NSTATES, 2), dtype=np.int32)
    out_bits = np.zeros((_NSTATES, 2, 3), dtype=np.uint8)
    for state in range(_NSTATES):
        for b in (0, 1):
            full = ((state << 1) | b) & ((1 << _CONV_K) - 1)
            ns = full & (_NSTATES - 1)
            next_state[state, b] = ns
            for i, poly in enumerate(_CONV_POLYS):
                out_bits[state, b, i] = bin(full & poly).count("1") % 2
    return next_state, out_bits


_TRELLIS_NS, _TRELLIS_OUT = _build_trellis()


def viterbi_decode(received, traceback=48):
    """Hard-decision Viterbi decode rate-1/3 K=7.

    Args:
        received: array of bits, length multiple of 3
        traceback: traceback depth

    Returns:
        decoded bits (without the K-1 flush bits)
    """
    received = np.asarray(received, dtype=np.uint8)
    n_steps = len(received) // 3
    if n_steps == 0:
        return np.array([], dtype=np.uint8)

    INF = 1e9
    metrics = np.full(_NSTATES, INF)
    metrics[0] = 0.0

    # Store survivor paths as bit decisions per state per step
    # (memory-heavy but fine for our frame sizes)
    paths = np.zeros((n_steps, _NSTATES), dtype=np.uint8)
    prev_state = np.zeros((n_steps, _NSTATES), dtype=np.int32)

    for t in range(n_steps):
        r = received[t * 3:(t + 1) * 3]
        new_metrics = np.full(_NSTATES, INF)
        for s in range(_NSTATES):
            if metrics[s] >= INF:
                continue
            for b in (0, 1):
                ns = _TRELLIS_NS[s, b]
                expected = _TRELLIS_OUT[s, b]
                dist = np.sum(expected != r)
                m = metrics[s] + dist
                if m < new_metrics[ns]:
                    new_metrics[ns] = m
                    paths[t, ns] = b
                    prev_state[t, ns] = s
        metrics = new_metrics

    # Traceback from best final state
    state = int(np.argmin(metrics))
    decoded = np.zeros(n_steps, dtype=np.uint8)
    for t in range(n_steps - 1, -1, -1):
        decoded[t] = paths[t, state]
        state = prev_state[t, state]

    # Strip K-1 flush bits
    return decoded[:n_steps - (_CONV_K - 1)]


# ---------------------------------------------------------------------------
# Reed-Solomon (255,223) decoder — Berlekamp-Massey
# ---------------------------------------------------------------------------
_RS_N = 255
_RS_K = 223
_RS_POLY = 0x11D

_gf_exp = [0] * 512
_gf_log = [0] * 256


def _gf_init():
    x = 1
    for i in range(255):
        _gf_exp[i] = x
        _gf_log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= _RS_POLY
    for i in range(255, 512):
        _gf_exp[i] = _gf_exp[i - 255]


_gf_init()


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _gf_exp[_gf_log[a] + _gf_log[b]]


def _gf_div(a, b):
    if a == 0:
        return 0
    return _gf_exp[(_gf_log[a] - _gf_log[b]) % 255]


def _gf_poly_mul(a, b):
    r = [0] * (len(a) + len(b) - 1)
    for i, ca in enumerate(a):
        for j, cb in enumerate(b):
            r[i + j] ^= _gf_mul(ca, cb)
    return r


def rs_decode_block(code255):
    """Decode one 255-byte RS codeword (parity-first format).

    Returns 223 data bytes or None.
    """
    assert len(code255) == _RS_N
    # Syndromes
    synd = []
    for i in range(_RS_N - _RS_K):
        s = 0
        for j in range(_RS_N):
            s ^= _gf_mul(code255[j], _gf_exp[(i * j) % 255])
        synd.append(s)
    if all(s == 0 for s in synd):
        return bytes(code255[_RS_N - _RS_K:])  # no errors, data is last 223

    # Berlekamp-Massey
    C = [1]
    B = [1]
    L = 0
    m = 1
    b = 1
    for n in range(len(synd)):
        d = synd[n]
        for i in range(1, L + 1):
            d ^= _gf_mul(C[i] if i < len(C) else 0, synd[n - i])
        if d == 0:
            m += 1
            continue
        T = C[:]
        coef = _gf_div(d, b)
        while len(C) < len(B) + m:
            C.append(0)
        for i in range(len(B)):
            C[i + m] ^= _gf_mul(coef, B[i])
        if 2 * L <= n:
            L = n + 1 - L
            B = T
            b = d
            m = 1
        else:
            m += 1

    # Find error positions (Chien search)
    err_pos = []
    for i in range(_RS_N):
        x = _gf_exp[(255 - i) % 255]
        y = 0
        for j, c in enumerate(C):
            y ^= _gf_mul(c, _gf_exp[(j * (255 - i)) % 255])
        if y == 0:
            err_pos.append(_RS_N - 1 - i)
    if len(err_pos) != L:
        return None  # too many errors

    # Forney (error magnitudes) — simplified for our use
    # Since we mostly test clean channels, do erasure-style correction
    # by solving the linear system for the known positions
    if L == 0:
        return bytes(code255[:_RS_K])

    # Build syndrome matrix and solve
    n_err = len(err_pos)
    # Vandermonde system: synd[i] = sum_j e_j * alpha^(i * pos_j)
    import copy
    # Use Gaussian elimination over GF(256)
    mat = []
    for i in range(n_err):
        row = [_gf_exp[(i * p) % 255] for p in err_pos] + [synd[i]]
        mat.append(row)
    # Eliminate
    for col in range(n_err):
        # Find pivot
        piv = -1
        for r in range(col, n_err):
            if mat[r][col] != 0:
                piv = r
                break
        if piv < 0:
            return None
        mat[col], mat[piv] = mat[piv], mat[col]
        inv = _gf_div(1, mat[col][col])
        mat[col] = [_gf_mul(v, inv) for v in mat[col]]
        for r in range(n_err):
            if r != col and mat[r][col] != 0:
                f = mat[r][col]
                mat[r] = [mat[r][c] ^ _gf_mul(f, mat[col][c])
                          for c in range(n_err + 1)]
    magnitudes = [mat[i][n_err] for i in range(n_err)]

    corrected = list(code255)
    for pos, mag in zip(err_pos, magnitudes):
        corrected[pos] ^= mag
    # Verify
    for i in range(_RS_N - _RS_K):
        s = 0
        for j in range(_RS_N):
            s ^= _gf_mul(corrected[j], _gf_exp[(i * j) % 255])
        if s != 0:
            return None
    return bytes(corrected[_RS_N - _RS_K:])


def rs_decode_bits(bits):
    """RS-decode a bit array (multiple of 255*8 bits). Returns data bits."""
    bits = np.asarray(bits, dtype=np.uint8)
    n_cw = len(bits) // (_RS_N * 8)
    out_bits = []
    for i in range(n_cw):
        cw_bits = bits[i * _RS_N * 8:(i + 1) * _RS_N * 8]
        cw_bytes = bytes(int("".join(map(str, cw_bits[j:j + 8])), 2)
                         for j in range(0, len(cw_bits), 8))
        decoded = rs_decode_block(cw_bytes)
        if decoded is None:
            return None
        for byte in decoded:
            out_bits.extend(int(b) for b in f"{byte:08b}")
    return np.array(out_bits, dtype=np.uint8)
