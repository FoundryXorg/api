#!/usr/bin/env python3
"""Font Foundry - automatic preview (1200x630) and pin (1000x1500) images.

  python scripts/render.py render   -> renders images for fonts that lack them, writes .marks.json
  python scripts/render.py mark     -> tells the Apps Script which images now exist

Env: SCRIPT_URL (Apps Script web app /exec), AUTOMATION_KEY, RAW_BASE (optional), MAX_PER_RUN (optional)
"""
import json, os, sys, tempfile, urllib.parse, urllib.request
from PIL import Image, ImageDraw, ImageFont

SCRIPT_URL = os.environ.get('SCRIPT_URL', '').strip()
KEY = os.environ.get('AUTOMATION_KEY', '').strip()
RAW_BASE = os.environ.get('RAW_BASE', 'https://raw.githubusercontent.com/FoundryXorg/api/main/')
MAX_PER_RUN = int(os.environ.get('MAX_PER_RUN', '40'))
MARKS = '.marks.json'
FAILED = 'scripts/failed.txt'

BN, EN = 'ফন্ট ফাউন্ড্রি', 'Font Foundry'
ANSI_BN, ANSI_DIGITS = 'Avgvi †mvbvi evsjv', '1234567890'   # keep in sync with ANSI_BN in the theme
UI_BOLD = ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf']
UI_REG = ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/dejavu/DejaVuSans.ttf']


def http(url, data=None, timeout=90):
    req = urllib.request.Request(url, data=data, headers={'User-Agent': 'font-foundry-action'})
    if data is not None:
        req.add_header('Content-Type', 'text/plain;charset=utf-8')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def first(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def ui(size, bold=True):
    p = first(UI_BOLD if bold else UI_REG)
    return ImageFont.truetype(p, size) if p else ImageFont.load_default()


def fnt(path, size):
    try:
        return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        return ImageFont.truetype(path, size)


def fit(path_or_fn, text, size, maxw, step=4):
    while size > 20:
        f = path_or_fn(size)
        if f.getlength(text) <= maxw:
            break
        size -= step
    return size


def samples(enc):
    if enc == 'ansi':
        return ANSI_BN, ANSI_DIGITS
    if enc == 'latin':
        return EN, 'ABCDEFG abcdefg 12345'
    return BN, EN


def preview(fp, name, enc):
    W, H = 1200, 630
    s1, s2 = ('ABCDEFGHIJKLM abcdefghijklm', EN + ' 1234567890') if enc == 'latin' else (ANSI_BN, ANSI_DIGITS) if enc == 'ansi' else (BN, EN)
    im = Image.new('RGB', (W, H), '#f6f3ed'); d = ImageDraw.Draw(im)
    d.rounded_rectangle((30, 30, W - 30, H - 30), 28, fill='#fffdf9', outline='#e6e0d5', width=2)
    d.text((80, 100), 'FONT FOUNDRY', font=ui(22), fill='#ff5b35', anchor='ls')
    z = fit(lambda s: ui(s), name, 52, W - 160)
    d.text((80, 170), name, font=ui(z), fill='#161616', anchor='ls')
    d.rectangle((80, 200, W - 80, 201), fill='#e6e0d5')
    z1 = fit(lambda s: fnt(fp, s), s1, 120, W - 160)
    d.text((80, 360), s1, font=fnt(fp, z1), fill='#161616', anchor='ls')
    z2 = fit(lambda s: fnt(fp, s), s2, 78, W - 160)
    d.text((80, 500), s2, font=fnt(fp, z2), fill='#4a4741', anchor='ls')
    d.text((80, 570), 'fontfoundry.blogspot.com', font=ui(20, False), fill='#77736b', anchor='ls')
    return im


def pin(fp, name, enc):
    W, H = 1000, 1500
    s1, s2 = samples(enc)
    im = Image.new('RGB', (W, H), '#f6f3ed'); d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 18), fill='#ff5b35')
    d.text((70, 100), 'FREE FONT DOWNLOAD', font=ui(28), fill='#ff5b35', anchor='ls')
    words = name.split(); l1, l2 = name, ''
    sz = fit(lambda s: ui(s), name, 88, W - 140)
    if sz < 56 and len(words) > 1:
        h = (len(words) + 1) // 2; l1, l2 = ' '.join(words[:h]), ' '.join(words[h:])
        sz = min(fit(lambda s: ui(s), l1, 88, W - 140), fit(lambda s: ui(s), l2, 88, W - 140))
    d.text((70, 210), l1, font=ui(sz), fill='#161616', anchor='ls')
    if l2:
        d.text((70, 210 + round(sz * 1.12)), l2, font=ui(sz), fill='#161616', anchor='ls')
    top = 210 + round(sz * 1.12) + 70 if l2 else 290
    d.rounded_rectangle((50, top, W - 50, 1190), 32, fill='#fffdf9', outline='#e6e0d5', width=3)
    d.text((90, top + 70), 'ENGLISH' if enc == 'latin' else 'BANGLA', font=ui(22), fill='#ff5b35', anchor='ls')
    mid = (top + 1190) // 2
    z1 = fit(lambda s: fnt(fp, s), s1, 150, W - 180)
    d.text((90, mid - 30), s1, font=fnt(fp, z1), fill='#161616', anchor='ls')
    z2 = fit(lambda s: fnt(fp, s), s2, 100, W - 180)
    d.text((90, mid + 150), s2, font=fnt(fp, z2), fill='#4a4741', anchor='ls')
    d.rectangle((0, 1260, W, H), fill='#20211f')
    d.text((70, 1360), 'Preview & download free', font=ui(40), fill='#ffffff', anchor='ls')
    d.text((70, 1420), 'fontfoundry.blogspot.com', font=ui(30, False), fill='#ff7655', anchor='ls')
    return im


def folder_of(path):
    p = str(path).split('/')
    return p[1] if len(p) >= 3 and p[0] == 'fonts' else 'unsorted'


def catalog():
    if os.environ.get('CATALOG_FILE'):
        return json.load(open(os.environ['CATALOG_FILE'], encoding='utf-8'))['fonts']
    d = json.loads(http(SCRIPT_URL))
    if not d.get('ok'):
        raise SystemExit('catalog failed')
    return d['fonts']


def font_bytes(f):
    if os.environ.get('FONT_DIR'):
        return open(os.path.join(os.environ['FONT_DIR'], os.path.basename(f['path'])), 'rb').read()
    p = str(f['path'])
    url = p if p.startswith('http') else RAW_BASE + '/'.join(urllib.parse.quote(x) for x in p.split('/'))
    return http(url, timeout=120)


def render():
    failed = set(open(FAILED).read().split()) if os.path.exists(FAILED) else set()
    todo = [f for f in catalog() if (not f.get('preview') or not f.get('pinImage')) and str(f['id']) not in failed]
    todo.sort(key=lambda f: str(f.get('createdAt') or ''), reverse=True)
    todo = todo[:MAX_PER_RUN]
    print('to render:', len(todo))
    marks, newfail = [], []
    for f in todo:
        fid, name, enc = str(f['id']), str(f.get('name') or f.get('fileName') or 'Font'), str(f.get('encoding') or 'unicode')
        try:
            ext = str(f['path']).rsplit('.', 1)[-1].lower()
            with tempfile.NamedTemporaryFile(suffix='.' + ext, delete=False) as t:
                t.write(font_bytes(f)); fp = t.name
            fold = folder_of(f['path']); item = {'id': fid}
            if not f.get('preview'):
                p = 'previews/%s/%s.png' % (fold, fid); os.makedirs(os.path.dirname(p), exist_ok=True)
                preview(fp, name, enc).save(p, optimize=True); item['preview'] = p
            if not f.get('pinImage'):
                p = 'pins/%s/%s.png' % (fold, fid); os.makedirs(os.path.dirname(p), exist_ok=True)
                pin(fp, name, enc).save(p, optimize=True); item['pinImage'] = p
            marks.append(item); print('ok', name)
        except Exception as e:
            print('FAILED', name, e); newfail.append(fid)
        finally:
            try: os.unlink(fp)
            except Exception: pass
    json.dump(marks, open(MARKS, 'w'))
    if newfail:
        with open(FAILED, 'a') as fh:
            fh.write('\n'.join(newfail) + '\n')


def mark():
    if not os.path.exists(MARKS):
        return
    items = json.load(open(MARKS))
    if not items:
        print('nothing to mark'); return
    if not (SCRIPT_URL and KEY):
        raise SystemExit('SCRIPT_URL / AUTOMATION_KEY missing')
    for i in range(0, len(items), 100):
        out = json.loads(http(SCRIPT_URL, json.dumps({'action': 'markImages', 'key': KEY, 'items': items[i:i + 100]}).encode()))
        print('mark:', out)
        if not out.get('ok'):
            raise SystemExit('mark failed: %s' % out)


if __name__ == '__main__':
    {'render': render, 'mark': mark}[sys.argv[1] if len(sys.argv) > 1 else 'render']()
