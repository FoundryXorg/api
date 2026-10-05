#!/usr/bin/env python3
"""Font Foundry - builds a static, crawlable website (one real HTML page per font) for GitHub Pages.

Run by .github/workflows/build-site.yml. Output goes to ./site and is deployed by GitHub Pages.
Env: SCRIPT_URL (Apps Script /exec), SITE_URL, APP_URL, RAW_BASE, GSC_VERIFY (optional Search Console tag)
"""
import html, json, os, re, shutil, urllib.parse, urllib.request
from datetime import datetime, timezone

VERSION = 'v1.6.1'
SCRIPT_URL = os.environ.get('SCRIPT_URL', '').strip()
SITE_URL = (os.environ.get('SITE_URL') or 'https://foundryxorg.github.io/api').rstrip('/')
APP_URL = (os.environ.get('APP_URL') or 'https://fontfoundry.blogspot.com').rstrip('/')
RAW_BASE = os.environ.get('RAW_BASE') or 'https://raw.githubusercontent.com/FoundryXorg/api/main/'
GSC_VERIFY = os.environ.get('GSC_VERIFY', '').strip()
_m = re.search(r'content\s*=\s*["\']([^"\']+)', GSC_VERIFY)       # accept the whole pasted <meta> tag too
GSC_VERIFY = (_m.group(1) if _m else GSC_VERIFY).strip().strip('"\'')
OUT = os.environ.get('OUT_DIR', 'site')
PER_PAGE = 60
BASE = urllib.parse.urlparse(SITE_URL).path.rstrip('/')          # '/api' on a project site, '' on a custom domain
BN, EN = 'ফন্ট ফাউন্ড্রি', 'Font Foundry'
ANSI_BN, DIGITS = 'Avgvi †mvbvi evsjv', '1234567890'          # keep in sync with ANSI_BN in the theme
NAME = 'Font Foundry'
esc = html.escape


def http(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'font-foundry-site-builder'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def catalog():
    if os.environ.get('CATALOG_FILE'):
        return json.load(open(os.environ['CATALOG_FILE'], encoding='utf-8'))['fonts']
    d = json.loads(http(SCRIPT_URL))
    if not d.get('ok') or not isinstance(d.get('fonts'), list):
        raise SystemExit('catalog failed')
    return d['fonts']


# ---------- helpers ----------
def slugify(s):
    return re.sub(r'^-+|-+$', '', re.sub(r'[^a-z0-9]+', '-', str(s or '').lower()))


def nm(f):
    return str(f.get('name') or f.get('fileName') or 'Font').strip()


def enc(f):
    e = str(f.get('encoding') or '').lower()
    return e if e in ('unicode', 'ansi', 'latin') else 'unicode'


def kind(f):
    return {'ansi': 'Bijoy / ANSI', 'latin': 'English'}.get(enc(f), 'Unicode Bangla')


def size_txt(f):
    b = float(f.get('fileSize') or 0)
    return ('%.2f MB' % (b / 1048576)) if b else 'n/a'


def dl(f):
    try:
        return int(float(f.get('downloadCount') or 0))
    except Exception:
        return 0


def day(f):
    s = str(f.get('createdAt') or '')
    m = re.match(r'\d{4}-\d\d-\d\d', s)
    return m.group(0) if m else ''


def u(path):                                    # absolute URL of a page on this site
    return SITE_URL + '/' + path.lstrip('/')


def href(path):                                 # site-root-relative link
    return BASE + '/' + path.lstrip('/')


def raw(path):
    p = str(path or '')
    return p if p.startswith('http') else RAW_BASE + '/'.join(urllib.parse.quote(x) for x in p.split('/'))


def samples(f):
    e = enc(f)
    if e == 'ansi':
        return ('BANGLA (ANSI)', ANSI_BN), ('NUMBERS', DIGITS)
    if e == 'latin':
        return ('ENGLISH', EN), ('NUMBERS', DIGITS)
    return ('BANGLA', BN), ('ENGLISH', EN)


def desc_for(f):
    t = 'Download %s, a free %s font. Preview it in %s, check the file size (%s), then download it free from %s.' % (
        nm(f), kind(f), 'English and numbers' if enc(f) == 'latin' else 'Bangla and English', size_txt(f), NAME)
    return t if len(t) <= 190 else t[:187] + '...'


CSS = """:root{--bg:#f6f3ed;--paper:#fffdf9;--ink:#161616;--muted:#6f6b63;--line:#e6e0d5;--accent:#ff5b35;--dark:#20211f}
@media(prefers-color-scheme:dark){:root{--bg:#111211;--paper:#191a18;--ink:#f5f2eb;--muted:#a8a39a;--line:#30312e;--accent:#ff7655;--dark:#0b0b0a}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Bengali","Hind Siliguri",sans-serif}
a{color:inherit;text-decoration:none}a:hover{color:var(--accent)}
.wrap{width:min(1120px,calc(100% - 32px));margin:auto}
header.top{border-bottom:1px solid var(--line);background:var(--bg)}
header.top .wrap{display:flex;align-items:center;gap:18px;flex-wrap:wrap;min-height:64px}
.logo{font-weight:800;font-size:19px;letter-spacing:-.03em;display:flex;align-items:center;gap:10px}
.logo i{display:grid;place-items:center;width:32px;height:32px;border-radius:9px;background:var(--ink);color:var(--bg);font:400 21px Georgia,serif;font-style:normal}
header.top nav{display:flex;gap:4px;flex-wrap:wrap;margin-left:auto}
header.top nav a{padding:7px 12px;border-radius:10px;font-size:14px;color:var(--muted)}
header.top nav a:hover{background:var(--paper);color:var(--ink)}
.crumbs{font-size:13px;color:var(--muted);margin:22px 0 6px}.crumbs a:hover{text-decoration:underline}
h1{font-size:clamp(28px,5vw,46px);line-height:1.1;letter-spacing:-.04em;margin:8px 0 10px}
h2{font-size:22px;letter-spacing:-.03em;margin:36px 0 14px}
.lead{color:var(--muted);max-width:720px;margin:0 0 20px}
.badge{display:inline-block;vertical-align:middle;font-size:12px;font-weight:700;padding:3px 10px;border-radius:99px;background:var(--paper);border:1px solid var(--line);color:var(--accent);letter-spacing:0;margin-left:6px}
.panel{background:var(--paper);border:1px solid var(--line);border-radius:20px;padding:22px;margin:18px 0}
.panel img.shot{display:block;width:100%;height:auto;border-radius:12px;border:1px solid var(--line);margin-bottom:18px}
.lbl{font-size:11px;font-weight:800;letter-spacing:.08em;color:var(--accent);margin-top:12px}
.sample{font-size:clamp(30px,6vw,60px);line-height:1.25;word-break:break-word;outline:none}
.sample.sm{font-size:clamp(24px,4vw,40px);color:var(--muted)}
dl.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:0}
dl.facts div{padding:12px 14px;border:1px solid var(--line);border-radius:14px;background:var(--paper)}
dl.facts dt{font-size:11px;font-weight:800;letter-spacing:.06em;color:var(--muted);text-transform:uppercase}dl.facts dd{margin:2px 0 0;font-weight:700}
.btns{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}
.btn{display:inline-block;padding:13px 22px;border-radius:14px;font-weight:700;background:var(--accent);color:#fff;border:0;font-size:16px;cursor:pointer}
.btn:hover{color:#fff;filter:brightness(1.08)}.btn.alt{background:var(--paper);color:var(--ink);border:1px solid var(--line)}.btn.alt:hover{color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px;padding:0;list-style:none;margin:0}
.card{display:block;background:var(--paper);border:1px solid var(--line);border-radius:18px;overflow:hidden;height:100%}
.card:hover{border-color:var(--accent)}
.card img{display:block;width:100%;height:auto;aspect-ratio:1200/630;object-fit:cover;background:var(--line)}
.card .noimg{display:grid;place-items:center;aspect-ratio:1200/630;background:var(--line);font:400 40px Georgia,serif;color:var(--muted)}
.card strong{display:block;padding:12px 14px 0;line-height:1.3}.card small{display:block;padding:2px 14px 14px;color:var(--muted)}
.pager{display:flex;gap:8px;flex-wrap:wrap;margin:26px 0}.pager a,.pager span{padding:8px 14px;border-radius:10px;border:1px solid var(--line);background:var(--paper);font-size:14px}
.pager span{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.cats{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.cats a{padding:9px 16px;border-radius:12px;border:1px solid var(--line);background:var(--paper);font-weight:600}
footer{margin-top:60px;padding:28px 0 40px;border-top:1px solid var(--line);color:var(--muted);font-size:14px}
footer .wrap{display:flex;gap:16px;flex-wrap:wrap;justify-content:space-between}
"""

ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%23ff5b35'/%3E%3Ctext x='32' y='46' font-size='40' text-anchor='middle' fill='white' font-family='Georgia,serif'%3EF%3C/text%3E%3C/svg%3E"


def layout(title, description, path, body, image='', ld=None, head=''):
    canon = u(path)
    tags = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>%s</title>' % esc(title),
        '<meta name="description" content="%s">' % esc(description, True),
        '<meta name="robots" content="index,follow,max-image-preview:large">',
        '<link rel="canonical" href="%s">' % esc(canon, True),
        '<link rel="icon" href="%s">' % ICON,
        '<meta name="theme-color" content="#ff5b35">',
        '<meta property="og:type" content="website"><meta property="og:site_name" content="%s">' % NAME,
        '<meta property="og:title" content="%s">' % esc(title, True),
        '<meta property="og:description" content="%s">' % esc(description, True),
        '<meta property="og:url" content="%s">' % esc(canon, True),
        ('<meta property="og:image" content="%s">' % esc(image, True)) if image else '',
        '<meta name="twitter:card" content="%s">' % ('summary_large_image' if image else 'summary'),
        ('<meta name="google-site-verification" content="%s">' % esc(GSC_VERIFY, True)) if GSC_VERIFY else '',
        '<link rel="stylesheet" href="%s">' % href('assets/s.css'),
        head,
        ('<script type="application/ld+json">%s</script>' % json.dumps(ld, ensure_ascii=False).replace('</', '<\\/')) if ld else '',
        '</head><body>',
        '<header class="top"><div class="wrap"><a class="logo" href="%s"><i>F</i>%s</a><nav aria-label="Main">'
        '<a href="%s">All fonts</a><a href="%s">Bangla fonts</a><a href="%s">English fonts</a><a href="%s">Most popular</a>'
        '<a href="%s">Open the full library</a></nav></div></header>' % (
            href(''), NAME, href('fonts/'), href('bangla/'), href('english/'), href('popular/'), esc(APP_URL, True)),
        '<main class="wrap">', body, '</main>',
        '<footer><div class="wrap"><span>&copy; %d %s &middot; Free Bangla and English fonts</span>'
        '<span><a href="%s">Library</a> &middot; <a href="%s">Bijoy / ANSI fonts</a> &middot; <a href="%s">Sitemap</a></span></div></footer>' % (
            datetime.now(timezone.utc).year, NAME, esc(APP_URL, True), href('ansi/'), href('sitemap.xml')),
        '</body></html>',
    ]
    return '\n'.join(t for t in tags if t)


def write(path, text):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as fh:
        fh.write(text)


# ---------- build ----------
def build():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    fonts = [f for f in catalog() if f.get('id') and (f.get('name') or f.get('fileName')) and f.get('path')]

    seen = {}
    for f in sorted(fonts, key=lambda x: str(x['id'])):          # same slug rules as the theme and the sitemap
        base = slugify(nm(f)) or 'font'
        s = base + '-' + str(f['id'])[-4:] if base in seen else base
        seen[s] = 1
        f['_slug'] = s
    fonts.sort(key=lambda x: str(x.get('createdAt') or ''), reverse=True)

    def img_url(f):                                              # prefer the copy served by this site, else GitHub raw
        p = str(f.get('preview') or '')
        if not p:
            return ''
        if os.path.exists(p):
            dst = os.path.join(OUT, p)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst):
                shutil.copy2(p, dst)
            return u(p)
        return raw(p)

    for f in fonts:
        f['_img'] = img_url(f)
    by_enc = {}
    for f in fonts:
        by_enc.setdefault(enc(f), []).append(f)

    def related(f, n=8):
        w = (re.split(r'[^a-z0-9ঀ-৿]+', nm(f).lower()) or [''])[0]
        sc = []
        for x in by_enc.get(enc(f), []):
            if x is f:
                continue
            s = 5.0 if (w and nm(x).lower().startswith(w)) else 0.0
            s += 1.0 / (1 + abs(float(x.get('fileSize') or 0) - float(f.get('fileSize') or 0)) / 50000.0)
            s += min(2.0, dl(x) / 50.0)
            sc.append((s, str(x['id']), x))
        sc.sort(key=lambda t: (-t[0], t[1]))
        return [t[2] for t in sc[:n]]

    def card(f):
        im = ('<img src="%s" alt="%s font preview" width="1200" height="630" loading="lazy" decoding="async">' % (esc(f['_img'], True), esc(nm(f), True))
              if f['_img'] else '<div class="noimg" aria-hidden="true">Aa</div>')
        return '<li><a class="card" href="%s">%s<strong>%s</strong><small>%s &middot; %s downloads</small></a></li>' % (
            href('font/%s/' % f['_slug']), im, esc(nm(f)), esc(kind(f)), format(dl(f), ','))

    pages = [('', None)]                                         # (path, lastmod) for the sitemap

    # ----- font pages -----
    for f in fonts:
        s1, s2 = samples(f)
        ext = str(f['path']).rsplit('.', 1)[-1].lower()
        fmt = 'opentype' if ext == 'otf' else 'truetype'
        path = 'font/%s/' % f['_slug']
        name = nm(f)
        title = '%s Font — Free Download & Preview | %s' % (name, NAME)
        rel = related(f)
        cat_path, cat_name = ('english/', 'English fonts') if enc(f) == 'latin' else ('bangla/', 'Bangla fonts')
        head = '<style>@font-face{font-family:"ffv";src:url("%s") format("%s");font-display:swap}</style>' % (esc(raw(f['path']), True), fmt)
        shot = ('<img class="shot" src="%s" alt="%s font preview" width="1200" height="630" fetchpriority="high">' % (esc(f['_img'], True), esc(name, True))) if f['_img'] else ''
        fname = str(f.get('fileName') or (name + '.' + ext))
        body = (
            '<nav class="crumbs" aria-label="Breadcrumb"><a href="%s">Home</a> &rsaquo; <a href="%s">%s</a> &rsaquo; %s</nav>'
            '<h1>%s <span class="badge">%s</span></h1><p class="lead">%s</p>'
            '<section class="panel" aria-label="Live preview">%s'
            '<div style="font-family:ffv,sans-serif">'
            '<div class="lbl">%s</div><div class="sample" contenteditable="true" spellcheck="false">%s</div>'
            '<div class="lbl">%s</div><div class="sample sm" contenteditable="true" spellcheck="false">%s</div></div>'
            '<p style="color:var(--muted);font-size:13px;margin:14px 0 0">Click the text to type your own words.</p></section>'
            '<div class="btns"><a class="btn" id="dl" href="%s" download="%s" rel="noopener">Download %s (%s)</a>'
            '<a class="btn alt" href="%s/?font=%s" rel="noopener">Open in the full library</a></div>'
            '<dl class="facts"><div><dt>Type</dt><dd>%s</dd></div><div><dt>Format</dt><dd>%s</dd></div><div><dt>File size</dt><dd>%s</dd></div>'
            '<div><dt>Downloads</dt><dd>%s</dd></div>%s</dl>'
            '%s'
        ) % (
            href(''), href(cat_path), esc(cat_name), esc(name), esc(name), esc(kind(f)), esc(desc_for(f)),
            shot, esc(s1[0]), esc(s1[1]), esc(s2[0]), esc(s2[1]),
            esc(raw(f['path']), True), esc(fname, True), ext.upper(), esc(size_txt(f)), esc(APP_URL, True), esc(f['_slug'], True),
            esc(kind(f)), ext.upper(), esc(size_txt(f)), format(dl(f), ','),
            ('<div><dt>Added</dt><dd>%s</dd></div>' % esc(day(f))) if day(f) else '',
            ('<h2>Related fonts</h2><ul class="grid">%s</ul>' % ''.join(card(x) for x in rel)) if rel else '')
        body += ('<script>(function(){var a=document.getElementById("dl");if(!a)return;a.addEventListener("click",function(e){'
                 'if(e.metaKey||e.ctrlKey||e.shiftKey||e.button===1)return;e.preventDefault();var u=a.href;'
                 'fetch(u).then(function(r){if(!r.ok)throw 0;return r.blob()}).then(function(b){var l=document.createElement("a");'
                 'l.href=URL.createObjectURL(b);l.download=a.getAttribute("download");document.body.appendChild(l);l.click();'
                 'setTimeout(function(){URL.revokeObjectURL(l.href);l.remove()},1500)}).catch(function(){window.open(u,"_blank")});'
                 'try{fetch(%s,{method:"POST",body:JSON.stringify({action:"increment",id:%s})}).catch(function(){})}catch(x){}'
                 '})})();</script>') % (json.dumps(SCRIPT_URL), json.dumps(str(f['id'])))
        ld = {'@context': 'https://schema.org', '@graph': [
            {'@type': 'BreadcrumbList', 'itemListElement': [
                {'@type': 'ListItem', 'position': 1, 'name': 'Home', 'item': u('')},
                {'@type': 'ListItem', 'position': 2, 'name': cat_name, 'item': u(cat_path)},
                {'@type': 'ListItem', 'position': 3, 'name': name, 'item': u(path)}]},
            {'@type': 'CreativeWork', 'name': name + ' font', 'description': desc_for(f), 'url': u(path),
             'isAccessibleForFree': True, 'encodingFormat': 'font/' + ext, 'publisher': {'@type': 'Organization', 'name': NAME},
             **({'image': f['_img']} if f['_img'] else {}), **({'dateCreated': day(f)} if day(f) else {})}]}
        write(path + 'index.html', layout(title, desc_for(f), path, body, f['_img'], ld, head))
        pages.append((path, day(f)))

    # ----- listing pages (paginated, plain links so crawlers can walk every font) -----
    def listing(dir_, h1, intro, items, title_base):
        total = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
        for n in range(1, total + 1):
            path = dir_ if n == 1 else '%spage/%d/' % (dir_, n)
            chunk = items[(n - 1) * PER_PAGE: n * PER_PAGE]
            pager = ''
            if total > 1:
                links = []
                for k in range(1, total + 1):
                    p = dir_ if k == 1 else '%spage/%d/' % (dir_, k)
                    links.append('<span aria-current="page">%d</span>' % k if k == n else '<a href="%s">%d</a>' % (href(p), k))
                pager = '<nav class="pager" aria-label="Pages">%s</nav>' % ''.join(links)
            body = '<h1>%s</h1><p class="lead">%s</p><ul class="grid">%s</ul>%s' % (
                esc(h1), esc(intro), ''.join(card(x) for x in chunk) or '<li>No fonts yet.</li>', pager)
            ttl = title_base + (' — Page %d' % n if n > 1 else '') + ' | ' + NAME
            write(path + 'index.html', layout(ttl, '%s %d fonts, each with a live preview.' % (intro, len(items)) if n == 1 else intro, path, body, chunk[0]['_img'] if chunk else ''))
            pages.append((path, ''))

    bangla = [f for f in fonts if enc(f) != 'latin']
    listing('fonts/', 'All fonts', 'Browse every free Bangla and English font in the library.', fonts, 'All Free Fonts')
    listing('bangla/', 'Bangla fonts', 'Free Bangla fonts, both Unicode and Bijoy / ANSI.', bangla, 'Free Bangla Fonts')
    listing('english/', 'English fonts', 'Free English (Latin) fonts.', by_enc.get('latin', []), 'Free English Fonts')
    listing('ansi/', 'Bijoy / ANSI Bangla fonts', 'Legacy Bijoy / ANSI Bangla fonts for use with Bijoy keyboards.', by_enc.get('ansi', []), 'Free Bijoy ANSI Fonts')
    listing('popular/', 'Most popular fonts', 'The most downloaded fonts in the library.',
            sorted(fonts, key=lambda x: (-dl(x), str(x['id']))), 'Most Popular Free Fonts')

    # ----- home -----
    latest = fonts[:24]
    top = sorted(fonts, key=lambda x: (-dl(x), str(x['id'])))[:12]
    body = (
        '<h1>Free Bangla &amp; English fonts</h1>'
        '<p class="lead">Preview every font in Bangla and English before you download. %s fonts and growing &mdash; new ones added all the time.</p>'
        '<div class="cats"><a href="%s">All fonts (%s)</a><a href="%s">Bangla (%s)</a><a href="%s">English (%s)</a><a href="%s">Bijoy / ANSI (%s)</a><a href="%s">Most popular</a></div>'
        '<h2>Latest fonts</h2><ul class="grid">%s</ul><p class="pager"><a href="%s">See all fonts &rarr;</a></p>'
        '<h2>Most popular</h2><ul class="grid">%s</ul>'
    ) % (format(len(fonts), ','), href('fonts/'), format(len(fonts), ','), href('bangla/'), format(len(bangla), ','),
         href('english/'), format(len(by_enc.get('latin', [])), ','), href('ansi/'), format(len(by_enc.get('ansi', [])), ','), href('popular/'),
         ''.join(card(x) for x in latest), href('fonts/'), ''.join(card(x) for x in top))
    ld = {'@context': 'https://schema.org', '@type': 'WebSite', 'name': NAME, 'url': u(''), 'alternateName': 'Font Foundry Bangla'}
    write('index.html', layout('%s — Free Bangla & English Fonts to Download' % NAME,
                               'Download free Bangla and English fonts. Preview every font in both scripts before you download. Unicode and Bijoy / ANSI Bangla fonts.',
                               '', body, latest[0]['_img'] if latest else '', ld))

    # ----- sitemap, robots, 404, assets, extra static files -----
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    rows = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p, last in pages:
        rows.append('<url><loc>%s</loc><lastmod>%s</lastmod></url>' % (esc(u(p)), last or now))
    rows.append('</urlset>')
    write('sitemap.xml', '\n'.join(rows))
    write('robots.txt', 'User-agent: *\nAllow: /\n\nSitemap: %s\n' % u('sitemap.xml'))
    write('404.html', layout('Page not found | ' + NAME, 'This page does not exist.', '404.html',
                             '<h1>Page not found</h1><p class="lead">That page does not exist. <a href="%s">Go to the home page</a> or <a href="%s">browse all fonts</a>.</p>' % (href(''), href('fonts/'))))
    write('assets/s.css', CSS)
    write('.nojekyll', '')
    if os.path.isdir('static'):                                   # e.g. a Google Search Console verification file
        shutil.copytree('static', OUT, dirs_exist_ok=True)
    print('built %s: %d fonts, %d pages' % (VERSION, len(fonts), len(pages)))


if __name__ == '__main__':
    build()
