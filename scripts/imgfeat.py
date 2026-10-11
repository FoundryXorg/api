"""Font Foundry v2.0 image-search features: 106 numbers measured from a picture of text.
Python reference for js (fontdesc.js features2). Order: S(36) ori3(36) hole(4) prof(24) zrun(6)."""
import numpy as np
from scipy import ndimage as ndi
import imgfont

HT = 40


def lines_of(ink):
    r = ink.sum(1)
    rows = np.flatnonzero(r > 0)
    if len(rows) == 0:
        return []
    out = []
    s = rows[0]
    p = rows[0]
    for y in rows[1:]:
        if y - p > 3:
            out.append((s, p + 1))
            s = y
        p = y
    out.append((s, p + 1))
    return [(a, b) for a, b in out if b - a >= 0.35 * HT]


def _prof_ori(ink, ls):
    prof = np.zeros(24)
    ori = np.zeros((3, 12))
    tot = 0
    f = ink.astype(np.float64)
    gx = ndi.correlate(f, imgfont.SOBEL_KX, mode='constant')
    gy = ndi.correlate(f, imgfont.SOBEL_KX.T, mode='constant')
    mag = np.hypot(gx, gy)
    th = np.arctan2(gy, gx) % np.pi
    bi = np.minimum((th / np.pi * 12).astype(int), 11)
    for a, b in ls:
        sub = ink[a:b]
        h = b - a
        w = sub.sum()
        rr = sub.sum(1).astype(np.float64)
        if h >= 24:
            pb = np.add.reduceat(rr, np.linspace(0, h, 25).astype(int)[:-1])
        else:
            pb = np.interp(np.linspace(0, h - 1, 24), np.arange(h), rr)
        prof += pb / max(1, pb.sum()) * w
        tot += w
        zy = np.minimum(((np.arange(h) + 0.5) / h * 3).astype(int), 2)
        for z in range(3):
            m = mag[a:b][zy == z]
            bb = bi[a:b][zy == z]
            ori[z] += np.bincount(bb.ravel(), weights=m.ravel(), minlength=12)
    prof /= max(1, tot)
    ori /= max(1e-9, ori.sum())
    return prof, ori.ravel()


def _holes_zruns(ink, ls):
    lab, n = ndi.label(~ink, structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]))
    holes = []
    if n:
        objs = ndi.find_objects(lab)
        H, W = ink.shape
        for i, sl in enumerate(objs):
            if sl[0].start == 0 or sl[1].start == 0 or sl[0].stop == H or sl[1].stop == W:
                continue
            area = (lab[sl] == i + 1).sum()
            if area < 4:
                continue
            holes.append((area / (HT * HT), (sl[1].stop - sl[1].start) / (sl[0].stop - sl[0].start)))
    _, nc = ndi.label(ink, structure=np.ones((3, 3)))
    nh = len(holes) / max(1, nc)
    ha = sorted(h[0] for h in holes)
    hr = sorted(h[1] for h in holes)
    hole = np.array([min(nh, 3) / 3, imgfont.pct(ha, 0.5), imgfont.pct(ha, 0.9), imgfont.pct(hr, 0.5)])
    zr = np.zeros(6)
    tot = np.zeros(6)
    for a, b in ls:
        sub = ink[a:b]
        h = b - a
        for z in range(3):
            za, zb = int(z * h / 3), int((z + 1) * h / 3)
            if zb <= za:
                continue
            z_ = sub[za:zb]
            rh = imgfont.runs_len(z_, 1)
            rv = imgfont.runs_len(z_, 0)
            rh = rh[rh <= 0.45 * HT]
            rv = rv[rv <= 0.45 * HT]
            zr[z] += (np.median(rh) / HT if len(rh) else 0) * h
            zr[3 + z] += (np.median(rv) / HT if len(rv) else 0) * h
            tot[z] += h
            tot[3 + z] += h
    return hole, zr / np.maximum(tot, 1)


def features(gray, invert=None):
    nm = imgfont.normalise(gray, invert)
    if nm is None:
        return None
    ink, lab, comps, big, p90 = nm
    ls = lines_of(ink)
    if not ls:
        return None
    s = imgfont.descriptor_core(ink, lab, comps, big, p90)
    prof, ori3 = _prof_ori(ink, ls)
    hole, zrun = _holes_zruns(ink, ls)
    v = np.concatenate([s, ori3, hole, prof, zrun]).astype(np.float64)
    return np.nan_to_num(v)
