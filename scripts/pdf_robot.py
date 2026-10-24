#!/usr/bin/env python3
"""Font Foundry PDF robot  v1.0.0

Phase "prepare" (before git push):
  1. Imports big files that were sent to the Telegram bot (over 20 MB, up to 95 MB): PDFs are copied into /pdf, fonts / .plp inside ZIPs are
     uploaded through the Apps Script, covers are rendered.
  2. Makes cover pictures + page counts for PDFs that do not have them yet (PDFs sent through the admin panel / small Telegram files).
Phase "register" (after git push): tells the Apps Script about the new PDF files and sends Telegram messages.

Needs (GitHub > Settings > Secrets and variables > Actions):
  SCRIPT_URL, AUTOMATION_KEY            (already used by the other robots)
  TG_BOT_TOKEN, TG_API_ID, TG_API_HASH  (only for big Telegram files; without them big files simply wait in the queue)
"""
import os, sys, re, json, time, base64, hashlib, zipfile, shutil, asyncio
import requests

SCRIPT_URL = os.environ.get('SCRIPT_URL', '').strip()
KEY = os.environ.get('AUTOMATION_KEY', '').strip()
TOKEN = os.environ.get('TG_BOT_TOKEN', '').strip()
API_ID = os.environ.get('TG_API_ID', '').strip()
API_HASH = os.environ.get('TG_API_HASH', '').strip()
RAW = 'https://raw.githubusercontent.com/FoundryXorg/api/main/'
STATE = os.environ.get('ROBOT_STATE', '/tmp/robot_state.json')
WORK = os.environ.get('ROBOT_WORK', '/tmp/robot_dl')
MAX_PDF = 95 * 1024 * 1024
MAX_SMALL = 25 * 1024 * 1024        # what the Apps Script can take for one font / .plp


def api(action, **kw):
    kw.update(action=action, key=KEY)
    for attempt in range(4):
        try:
            r = requests.post(SCRIPT_URL, data=json.dumps(kw), timeout=300)
            return r.json()
        except Exception as e:                      # noqa
            print('api error', action, e)
            time.sleep(5 * (attempt + 1))
    return {'ok': False, 'error': 'no answer from Apps Script'}


def say(chat, mid, text):
    if not (TOKEN and chat):
        return
    try:
        requests.post('https://api.telegram.org/bot%s/sendMessage' % TOKEN, json={'chat_id': chat, 'text': text[:3800], 'reply_to_message_id': int(mid) if mid else None, 'allow_sending_without_reply': True, 'disable_web_page_preview': True}, timeout=30)
    except Exception as e:                          # noqa
        print('telegram error', e)


def slug(s):
    s = re.sub(r'[^a-z0-9]+', '-', str(s).lower()).strip('-')[:40]
    return s or 'pdf'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def inspect_pdf(path, cover_path):
    """returns (pages, title, ratio). Writes a JPEG cover (600 px wide) to cover_path; a grey 'PDF' card when the file cannot be rendered."""
    import fitz
    pages, title, ratio = 0, '', 0.0
    try:
        doc = fitz.open(path)
        pages = doc.page_count
        title = (doc.metadata or {}).get('title', '') or ''
        if doc.needs_pass:
            raise RuntimeError('encrypted')
        page = doc[0]
        w, h = page.rect.width, page.rect.height
        pix = page.get_pixmap(matrix=fitz.Matrix(600.0 / w, 600.0 / w), alpha=False)
        os.makedirs(os.path.dirname(cover_path), exist_ok=True)
        pix.save(cover_path, jpg_quality=80)
        ratio = round(w / h, 3)
        doc.close()
    except Exception as e:                          # noqa
        print('cover fallback', path, e)
        try:
            d = fitz.open()
            pg = d.new_page(width=600, height=800)
            pg.draw_rect(pg.rect, color=None, fill=(0.93, 0.9, 0.86))
            pg.insert_text((190, 430), 'PDF', fontsize=110, color=(0.85, 0.3, 0.2))
            os.makedirs(os.path.dirname(cover_path), exist_ok=True)
            pg.get_pixmap(alpha=False).save(cover_path, jpg_quality=80)
            ratio = 0.75
        except Exception as e2:                     # noqa
            print('placeholder failed', e2)
            return pages, title, 0.0
    return pages, title, ratio


def parse_caption(caption, fallback_title):
    parts = [x.strip() for x in str(caption or '').split('|')]
    return (parts[0] if parts and parts[0] else fallback_title), (parts[1] if len(parts) > 1 else ''), (parts[2] if len(parts) > 2 else ''), (parts[3] if len(parts) > 3 else '')


def add_pdf(src, name, job, from_zip, state):
    """copies one PDF into the repo tree; returns a message line"""
    size = os.path.getsize(src)
    base = re.sub(r'\.pdf$', '', name, flags=re.I)
    pretty = re.sub(r'\s+', ' ', re.sub(r'[_\-]+', ' ', base)).strip() or 'PDF'
    if size > MAX_PDF:
        return '❌ %s (%d MB: over the %d MB limit of GitHub hosting)' % (name, size // 1048576, MAX_PDF // 1048576)
    h = sha256(src)
    title, author, tags, cat = parse_caption(job.get('caption', ''), pretty)
    if from_zip:
        title = pretty
    chk = api('pdfDup', hash=h, title=title, author=author)
    if chk.get('dup'):
        return '⏭️ %s (already in PDFs: %s)' % (title, chk.get('reason'))
    folder = 'big-' + time.strftime('%Y%m')
    rel = 'pdf/%s/%s-%s.pdf' % (folder, slug(title), h[:10])
    cov = 'pdf-previews/%s.jpg' % h[:16]
    os.makedirs(os.path.dirname(rel), exist_ok=True)
    shutil.copyfile(src, rel)
    pages, mtitle, ratio = inspect_pdf(rel, cov)
    if not job.get('caption') and mtitle and not from_zip and len(mtitle) > 3:
        title = mtitle.strip()[:120]
    state['pdfs'].append({'job': job['id'], 'title': title, 'author': author, 'tags': tags, 'category': cat, 'fileName': name, 'path': rel,
                          'preview': cov if os.path.exists(cov) else '', 'fileSize': size, 'hash': h, 'pages': pages, 'ratio': ratio})
    return None


def handle_file(path, name, job, state, lines):
    low = name.lower()
    if low.endswith('.pdf'):
        m = add_pdf(path, name, job, False, state)
        if m:
            lines.append(m)
    elif low.endswith('.zip'):
        try:
            z = zipfile.ZipFile(path)
        except Exception:                           # noqa
            lines.append('❌ %s (cannot open ZIP)' % name)
            return
        n = 0
        okc = {'font': 0, 'plp': 0, 'pdf': 0}
        for info in z.infolist():
            en = info.filename
            if info.is_dir() or re.search(r'(^|/)(__MACOSX/|\._)', en):
                continue
            leaf = en.split('/')[-1]
            ll = leaf.lower()
            if not re.search(r'\.(ttf|otf|plp|pdf)$', ll):
                continue
            n += 1
            tmp = os.path.join(WORK, 'z_' + job['id'] + '_' + str(n) + '_' + slug(leaf))
            with z.open(info) as src, open(tmp, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            if ll.endswith('.pdf'):
                m = add_pdf(tmp, leaf, job, True, state)
                if m:
                    lines.append(m)
                else:
                    okc['pdf'] += 1
            else:
                r = upload_small(tmp, leaf, job)
                lines.append(r[1]) if r[1] else None
                if r[0]:
                    okc['plp' if ll.endswith('.plp') else 'font'] += 1
            os.remove(tmp)
        if not n:
            lines.append('⏭️ %s (no .ttf / .otf / .plp / .pdf inside)' % name)
        else:
            lines.append('✅ %s: %d fonts, %d templates, %d PDFs added' % (name, okc['font'], okc['plp'], okc['pdf']))
    elif re.search(r'\.(ttf|otf|plp)$', low):
        r = upload_small(path, name, job)
        lines.append(r[1] or ('✅ ' + name))
    else:
        lines.append('⏭️ %s (not a font, .plp, PDF or ZIP)' % name)


def upload_small(path, name, job):
    """font / .plp through the Apps Script (it detects name, language, thumb). Returns (ok, message-or-None)"""
    if os.path.getsize(path) > MAX_SMALL:
        return False, '❌ %s (over 25 MB: a single font / template cannot be that big)' % name
    with open(path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    act = 'autoPlp' if name.lower().endswith('.plp') else 'autoFont'
    out = {}
    for a in range(3):
        out = api(act, content=b64, fileName=name, caption=job.get('caption', '') if not name.lower().endswith('.zip') else '')
        if out.get('ok') or not out.get('retry'):
            break
        time.sleep(5 * (a + 1))
    if out.get('ok'):
        return True, None
    if out.get('error') == 'duplicate':
        return False, None                          # already there: stay quiet inside big ZIPs
    return False, '❌ %s (%s)' % (name, out.get('error'))


async def download_all(jobs):
    from pyrogram import Client
    got = {}
    async with Client('ffrobot', api_id=int(API_ID), api_hash=API_HASH, bot_token=TOKEN, in_memory=True, no_updates=True) as app:
        for j in jobs:
            d = os.path.join(WORK, j['id'])
            os.makedirs(d, exist_ok=True)
            try:
                p = await app.download_media(j['file_id'], file_name=os.path.join(d, re.sub(r'[\\/]+', '_', j['name'])))
                got[j['id']] = str(p) if p else None
            except Exception as e:                  # noqa
                print('download failed', j['name'], e)
                got[j['id']] = None
    return got


def prepare():
    os.makedirs(WORK, exist_ok=True)
    state = {'pdfs': [], 'covers': [], 'jobs': {}}
    if not (SCRIPT_URL and KEY):
        print('SCRIPT_URL / AUTOMATION_KEY missing')
        json.dump(state, open(STATE, 'w'))
        return
    # 1) big Telegram files
    jobs = api('bigJobs').get('jobs') or []
    if jobs and not (TOKEN and API_ID and API_HASH):
        print('%d big file(s) are waiting, but TG_BOT_TOKEN / TG_API_ID / TG_API_HASH are not set' % len(jobs))
        jobs = []
    if jobs:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        files = loop.run_until_complete(download_all(jobs))
        for j in jobs:
            lines = []
            p = files.get(j['id'])
            if not p or not os.path.exists(p):
                lines.append('❌ %s (could not download it from Telegram)' % j['name'])
            else:
                try:
                    handle_file(p, j['name'], j, state, lines)
                except Exception as e:              # noqa
                    lines.append('❌ %s (%s)' % (j['name'], str(e)[:80]))
                try:
                    os.remove(p)
                except OSError:
                    pass
            state['jobs'][j['id']] = {'chat': j['chat'], 'mid': j['mid'], 'name': j['name'], 'lines': lines}
    # 2) covers for PDFs that have none
    for it in (api('autoPdfPending').get('pdfs') or [])[:15]:
        if any(x['path'] == it['path'] for x in state['pdfs']):
            continue
        tmp = os.path.join(WORK, 'c_' + it['id'] + '.pdf')
        try:
            r = requests.get(RAW + it['path'], timeout=300)
            if r.status_code != 200 or len(r.content) < 100:
                print('not downloadable yet', it['path'])
                continue
            open(tmp, 'wb').write(r.content)
            cov = 'pdf-previews/%s.jpg' % it['id']
            pages, _t, ratio = inspect_pdf(tmp, cov)
            state['covers'].append({'id': it['id'], 'preview': cov if os.path.exists(cov) else '', 'pages': pages, 'ratio': ratio})
        except Exception as e:                      # noqa
            print('cover failed', it['path'], e)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    json.dump(state, open(STATE, 'w'))
    print('prepared: %d new PDFs, %d covers, %d big jobs' % (len(state['pdfs']), len(state['covers']), len(state['jobs'])))


def register():
    if not os.path.exists(STATE):
        return
    state = json.load(open(STATE))
    for c in state['covers']:
        api('autoPdfCover', id=c['id'], preview=c['preview'], pages=c['pages'], ratio=c['ratio'])
    for p in state['pdfs']:
        out = {}
        for a in range(5):                          # the file may need a moment to appear on GitHub after the push
            out = api('autoPdf', **{k: v for k, v in p.items() if k != 'job'})
            if out.get('ok') or not out.get('retry'):
                break
            time.sleep(15)
        job = state['jobs'].get(p['job'])
        if job is not None:
            if out.get('ok'):
                job['lines'].append('\U0001F4D5 %s — PDF added (%d pages, %.1f MB)' % (p['title'], p['pages'], p['fileSize'] / 1048576.0))
            elif out.get('error') == 'duplicate':
                job['lines'].append('⏭️ %s (already in PDFs)' % p['title'])
            else:
                job['lines'].append('❌ %s (%s)' % (p['title'], out.get('error')))
    for jid, job in state['jobs'].items():
        ok = not any(l.startswith('❌') for l in job['lines'])
        say(job['chat'], job['mid'], '\U0001F4E6 ' + job['name'] + '\n' + '\n'.join(job['lines'][:30]))
        api('bigDone', id=jid, status='done' if ok else 'failed')
    print('registered')


if __name__ == '__main__':
    {'prepare': prepare, 'register': register}[sys.argv[1] if len(sys.argv) > 1 else 'prepare']()
