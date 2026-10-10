"""Font style descriptor: text-independent numbers measured from a picture of text.
Deliberately simple (integer-ish maths, no library tricks) so it can be re-implemented 1:1 in JavaScript."""
import numpy as np
from scipy import ndimage as ndi

H_TARGET = 40.0
MAX_PIXELS = 1_200_000
NAMES = []


def otsu(gray):
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    sum_all = (hist * np.arange(256)).sum()
    wb = 0.0; sb = 0.0; best = -1.0; thr = 127
    for t in range(256):
        wb += hist[t]
        if wb == 0: continue
        wf = total - wb
        if wf == 0: break
        sb += t * hist[t]
        mb = sb / wb; mf = (sum_all - sb) / wf
        v = wb * wf * (mb - mf) ** 2
        if v > best: best = v; thr = t
    return thr


def binarize(gray, invert=None):
    t = otsu(gray)
    dark = gray <= t
    if invert is None:
        ink = ~dark if dark.sum() * 2 > dark.size else dark
    else:
        ink = dark if not invert else ~dark
    return ink


def box2(g):
    h, w = g.shape
    h2, w2 = h // 2, w // 2
    if h2 < 1 or w2 < 1: return g
    g = g[:h2 * 2, :w2 * 2].astype(np.float64)
    return (g[0::2, 0::2] + g[1::2, 0::2] + g[0::2, 1::2] + g[1::2, 1::2]) / 4.0


def bilinear(g, s):
    h, w = g.shape
    nh, nw = max(1, int(round(h * s))), max(1, int(round(w * s)))
    ys = np.clip((np.arange(nh) + 0.5) / s - 0.5, 0, h - 1)
    xs = np.clip((np.arange(nw) + 0.5) / s - 0.5, 0, w - 1)
    y0 = np.floor(ys).astype(int); x0 = np.floor(xs).astype(int)
    y1 = np.minimum(y0 + 1, h - 1); x1 = np.minimum(x0 + 1, w - 1)
    fy = (ys - y0)[:, None]; fx = (xs - x0)[None, :]
    g = g.astype(np.float64)
    top = g[y0][:, x0] * (1 - fx) + g[y0][:, x1] * fx
    bot = g[y1][:, x0] * (1 - fx) + g[y1][:, x1] * fx
    return top * (1 - fy) + bot * fy


def resize_gray(gray, s):
    g = gray.astype(np.float64)
    while s <= 0.5:
        g = box2(g); s *= 2
    if abs(s - 1) > 1e-6:
        g = bilinear(g, s)
    return np.clip(np.floor(g + 0.5), 0, 255).astype(np.uint8)


def pct(sorted_arr, p):
    n = len(sorted_arr)
    if n == 0: return 0.0
    return float(sorted_arr[min(n - 1, int(p * (n - 1) + 1e-9))])


def components(ink):
    lab, n = ndi.label(ink, structure=np.ones((3, 3), int))
    if n == 0: return lab, []
    objs = ndi.find_objects(lab)
    areas = ndi.sum(ink, lab, index=np.arange(1, n + 1))
    comps = []
    for i, sl in enumerate(objs):
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        comps.append((i + 1, x0, y0, x1 - x0, y1 - y0, int(areas[i])))
    return lab, comps


def runs_len(mask, axis):
    """lengths of all ink runs along rows (axis=1) or columns (axis=0)"""
    m = mask if axis == 1 else mask.T
    pad = np.zeros((m.shape[0], 1), bool)
    d = np.diff(np.concatenate([pad, m, pad], axis=1).astype(np.int8), axis=1)
    out = []
    for r in range(m.shape[0]):
        row = d[r]
        st = np.flatnonzero(row == 1); en = np.flatnonzero(row == -1)
        out.append(en - st)
    return np.concatenate(out) if out else np.zeros(0, int)


def normalise(gray, invert=None):
    """returns (ink mask at normalised scale, comps, labels, big component list) or None"""
    g = gray
    while g.shape[0] * g.shape[1] > MAX_PIXELS * 4 and min(g.shape) > 8:
        g = np.clip(np.floor(box2(g) + 0.5), 0, 255).astype(np.uint8)
    for _ in range(2):
        ink = binarize(g, invert)
        lab, comps = components(ink)
        comps = [c for c in comps if c[5] >= 6]
        if len(comps) < 3: return None
        hs = sorted(c[4] for c in comps)
        p90 = pct(hs, 0.9)
        main = sorted(c[4] for c in comps if c[4] >= 0.4 * p90)
        href = pct(main, 0.5)
        if href < 2: return None
        s = H_TARGET / href
        s = min(s, max(0.2, np.sqrt(MAX_PIXELS / (g.shape[0] * g.shape[1]))))
        if 0.8 <= s <= 1.25: break
        g = resize_gray(g, s)
    ink = binarize(g, invert)
    lab, comps = components(ink)
    comps = [c for c in comps if c[5] >= 6]
    if len(comps) < 3: return None
    hs = sorted(c[4] for c in comps)
    p90 = pct(hs, 0.9)
    big = [c for c in comps if c[4] >= 0.4 * p90]
    return ink, lab, comps, big, p90


SOBEL_KX = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], float)


def orient_hist(ink, bins=12):
    f = ink.astype(np.float64)
    gx = ndi.correlate(f, SOBEL_KX, mode='constant', cval=0)
    gy = ndi.correlate(f, SOBEL_KX.T, mode='constant', cval=0)
    mag = np.hypot(gx, gy)
    th = np.arctan2(gy, gx) % np.pi
    idx = np.minimum((th / np.pi * bins).astype(int), bins - 1)
    h = np.bincount(idx.ravel(), weights=mag.ravel(), minlength=bins)
    s = h.sum()
    return h / s if s > 0 else h


def slant_angle(ink, big_ids=None):
    best = None; best_a = 0.0
    ys, xs = np.nonzero(ink)
    if len(ys) == 0: return 0.0
    h = ink.shape[0]
    scores = []
    angles = np.arange(-30, 30.01, 2.5)
    yc = ys - h / 2.0
    for a in angles:
        k = np.tan(np.deg2rad(a))
        xx = np.floor(xs + yc * k + 0.5).astype(int)
        xx -= xx.min()
        proj = np.bincount(xx)
        scores.append(float((proj.astype(np.float64) ** 2).sum()))
    scores = np.array(scores)
    i = int(scores.argmax())
    a = angles[i]
    if 0 < i < len(angles) - 1:
        y0, y1, y2 = scores[i - 1], scores[i], scores[i + 1]
        den = (y0 - 2 * y1 + y2)
        if den != 0:
            a += 2.5 * 0.5 * (y0 - y2) / den
    return float(a)


def serif_stats(ink, lab, big):
    ratios = []
    for (cid, x0, y0, w, h, area) in big:
        if h < 0.5 * H_TARGET: continue
        sub = (lab[y0:y0 + h, x0:x0 + w] == cid)
        band = max(2, int(round(0.07 * h)))
        bot = sub[h - band:, :].sum() / band
        m0 = int(0.45 * h); m1 = max(m0 + 2, int(0.55 * h))
        mid = sub[m0:m1, :].sum() / max(1, (m1 - m0))
        if mid <= 0: continue
        ratios.append(bot / mid)
    ratios.sort()
    return pct(ratios, 0.25), pct(ratios, 0.5), pct(ratios, 0.75)


def gaps(big):
    cs = sorted(big, key=lambda c: c[1])
    out = []
    for i, a in enumerate(cs):
        ax1 = a[1] + a[3]
        best = None
        for b in cs[i + 1:i + 6]:
            if b[1] < ax1 - 1: continue
            ov = min(a[2] + a[4], b[2] + b[4]) - max(a[2], b[2])
            if ov < 0.3 * min(a[4], b[4]): continue
            g = b[1] - ax1
            if best is None or g < best: best = g
            break
        if best is not None and best <= 0.8 * H_TARGET:
            out.append(best / H_TARGET)
    out.sort()
    return pct(out, 0.5), len(out)


def long_run_frac(ink):
    """fraction of ink rows' ink that sits in very long horizontal runs (Bangla headline / matra)"""
    r = runs_len(ink, 1)
    if len(r) == 0: return 0.0
    tot = r.sum()
    return float(r[r >= 1.2 * H_TARGET].sum() / tot) if tot else 0.0


def descriptor(gray, invert=None, return_names=False):
    nm = normalise(gray, invert)
    if nm is None: return None
    ink, lab, comps, big, p90 = nm
    names = []; v = []
    def add(name, x): names.append(name); v.append(float(x))
    rh = runs_len(ink, 1); rv = runs_len(ink, 0)
    rh = np.sort(rh[(rh <= 0.45 * H_TARGET)]); rv = np.sort(rv[(rv <= 0.45 * H_TARGET)])
    sv = [pct(rh, p) / H_TARGET for p in (0.25, 0.5, 0.75)]
    sh = [pct(rv, p) / H_TARGET for p in (0.25, 0.5, 0.75)]
    for p, x in zip(('25', '50', '75'), sv): add('stem' + p, x)
    for p, x in zip(('25', '50', '75'), sh): add('bar' + p, x)
    add('contrast', (sh[1] + 1e-3) / (sv[1] + 1e-3))
    add('slant', slant_angle(ink) / 30.0)
    asp = sorted(c[3] / c[4] for c in big)
    for p in (0.25, 0.5, 0.75): add('aspect%d' % int(p * 100), pct(asp, p))
    fill = sorted(c[5] / (c[3] * c[4]) for c in big)
    for p in (0.25, 0.5, 0.75): add('fill%d' % int(p * 100), pct(fill, p))
    hs = sorted(c[4] for c in big)
    for p in (0.1, 0.25, 0.5, 0.75): add('h%d' % int(p * 100), pct(hs, p) / max(1.0, p90))
    g, ng = gaps(big)
    add('gap', g)
    area = float(ink.sum())
    stem = max(1.0, sv[1] * H_TARGET)
    add('conn', len(big) / max(1.0, (area / stem) / H_TARGET))
    s25, s50, s75 = serif_stats(ink, lab, big)
    add('serif25', s25); add('serif50', s50); add('serif75', s75)
    add('headline', long_run_frac(ink))
    oh = orient_hist(ink)
    for i, x in enumerate(oh): add('ori%d' % i, x)
    arr = np.array(v, np.float64)
    arr = np.nan_to_num(arr)
    return (arr, names) if return_names else arr
