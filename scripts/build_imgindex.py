#!/usr/bin/env python3
"""Font Foundry v1.9.0 - builds imgindex/index.json for "Search fonts by image".

For every font in the catalog it renders three sample lines, measures the 36 style numbers
(scripts/imgfont.py - same maths as the browser), projects them with the pre-trained model
(imgindex/model.json) and stores 12 small numbers per font. Only NEW fonts are processed on later runs.

Env: SCRIPT_URL (Apps Script /exec), RAW_BASE (optional), CATALOG_FILE (optional, testing), WORKERS (optional)
"""
import base64, io, json, os, sys, time, urllib.request
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imgfont import descriptor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_URL = os.environ.get('SCRIPT_URL', '').strip()
RAW_BASE = os.environ.get('RAW_BASE') or 'https://raw.githubusercontent.com/FoundryXorg/api/main/'
OUT = os.path.join(ROOT, 'imgindex', 'index.json')
MODEL = json.load(open(os.path.join(ROOT, 'imgindex', 'model.json'), encoding='utf-8'))
TEXTS = {
    'bn': ["আমার সোনার বাংলা আমি তোমায় ভালোবাসি", "বাংলাদেশের স্বাধীনতা সংগ্রামের ইতিহাস গৌরবের", "শিক্ষা ও গবেষণা কেন্দ্র ঢাকা চট্টগ্রাম"],
    'ansi': ["Avgvi †mvbvi evsjv Avwg †Zvgvq fv‡jvevwm", "evsjv fvlv Avgvi gv‡qi fvlv", "evsjv‡`‡ki my›`i cÖK…wZ"],
    'en': ["The quick brown fox jumps over the lazy dog 0123456789", "Sphinx of black quartz, judge my vow", "Pack my box with five dozen liquor jugs"],
}
GROUP = {'unicode': 'bn', 'ansi': 'ansi', 'latin': 'en'}
NEED = {'bn': [0x0995, 0x09BE, 0x09AE], 'ansi': [0x41, 0x2020, 0x61], 'en': [0x41, 0x61]}


def http(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'font-foundry-imgindex'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def catalog():
    if os.environ.get('CATALOG_FILE'):
        return json.load(open(os.environ['CATALOG_FILE'], encoding='utf-8'))['fonts']
    d = json.loads(http(SCRIPT_URL))
    if not d.get('ok') or not isinstance(d.get('fonts'), list):
        raise SystemExit('catalog failed')
    return d['fonts']


def font_source(path):
    local = os.path.join(ROOT, path)
    return local if os.path.exists(local) else io.BytesIO(http(RAW_BASE + path))


def covered(src, group):
    from fontTools.ttLib import TTFont
    if hasattr(src, 'seek'): src.seek(0)
    cm = TTFont(src, fontNumber=0, lazy=True).getBestCmap() or {}
    return all(c in cm for c in NEED[group])


def render(src, text, size=80, pad=30):
    if hasattr(src, 'seek'): src.seek(0)
    try:
        f = ImageFont.truetype(src, size, layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        if hasattr(src, 'seek'): src.seek(0)
        f = ImageFont.truetype(src, size)
    l, t, r, b = f.getbbox(text)
    im = Image.new('RGB', (r - l + 2 * pad, b - t + 2 * pad), 255)
    ImageDraw.Draw(im).text((pad - l, pad - t), text, font=f, fill=0)
    a = np.asarray(im, dtype=np.uint32)
    return ((a[..., 0] * 19595 + a[..., 1] * 38470 + a[..., 2] * 7471 + 0x8000) >> 16).astype(np.uint8)


def job(item):
    fid, path, group = item
    try:
        src = font_source(path)
        if not covered(src, group): return fid, None
        ds = []
        for t in TEXTS[group]:
            try:
                d = descriptor(render(src, t))
                if d is not None: ds.append(d)
            except Exception:
                pass
        if not ds: return fid, None
        m = MODEL['groups'][group]
        z = (np.mean(ds, axis=0) - np.array(m['mean'])) / np.array(m['std'])
        p = z @ np.array(m['W'])
        return fid, np.clip(np.round(p / m['scale']), -127, 127).astype(np.int8).tolist()
    except Exception as e:
        print('skip', fid, path, type(e).__name__, str(e)[:80])
        return fid, None


def main():
    t0 = time.time()
    fonts = [f for f in catalog() if f.get('id') and f.get('path') and str(f['path']).lower().rsplit('.', 1)[-1] in ('ttf', 'otf', 'ttc')]
    old = {}
    if os.path.exists(OUT):
        try:
            o = json.load(open(OUT, encoding='utf-8'))
            if o.get('model', {}).get('v') == MODEL['v']:
                for g, gd in o['groups'].items():
                    raw = np.frombuffer(base64.b64decode(gd['q']), dtype=np.int8).reshape(-1, MODEL['k'])
                    for i, fid in enumerate(gd['ids']): old[(g, fid)] = raw[i].tolist()
                old_bad = set(o.get('skipped', []))
            else:
                old_bad = set()
        except Exception:
            old_bad = set()
    else:
        old_bad = set()
    work, keep, bad = [], {}, set()
    for f in fonts:
        fid = str(f['id']); g = GROUP.get(str(f.get('encoding') or 'unicode').lower(), 'bn')
        if (g, fid) in old: keep[(g, fid)] = old[(g, fid)]
        elif fid in old_bad: bad.add(fid)
        else: work.append((fid, f['path'], g))
    print('catalog', len(fonts), '| reused', len(keep), '| new', len(work))
    gof = {w[0]: w[2] for w in work}
    with Pool(int(os.environ.get('WORKERS', '4'))) as pool:
        for n, (fid, v) in enumerate(pool.imap_unordered(job, work, chunksize=4), 1):
            if v is None: bad.add(fid)
            else: keep[(gof[fid], fid)] = v
            if n % 500 == 0: print(n, '/', len(work), round(time.time() - t0), 's', flush=True)
    groups = {}
    for g in ('bn', 'ansi', 'en'):
        items = sorted((fid, v) for (gg, fid), v in keep.items() if gg == g)
        groups[g] = {'ids': [i for i, _ in items], 'q': base64.b64encode(np.array([v for _, v in items], dtype=np.int8).tobytes()).decode()}
    out = {'v': 1, 'built': time.strftime('%Y-%m-%d'), 'model': MODEL, 'groups': groups, 'skipped': sorted(bad)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), separators=(',', ':'))
    print('wrote', OUT, os.path.getsize(OUT), 'bytes;', {g: len(groups[g]['ids']) for g in groups}, 'skipped', len(bad), round(time.time() - t0), 's')


if __name__ == '__main__':
    main()
