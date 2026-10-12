#!/usr/bin/env python3
"""Font Foundry v2.0.0 - self-training image-search robot.

Runs inside GitHub Actions. It needs no manual training:
  1. reads the font catalog (Apps Script) and the font files of this repo,
  2. if there is no trained model yet (or the library grew a lot) it TRAINS a small neural network from the fonts themselves
     (renders sample text with every chosen font, measures 106 style numbers, learns to tell fonts apart),
  3. gives every font a 192-number "fingerprint" and saves imgindex/bn.json (Bangla: Unicode + Bijoy) and imgindex/en.json (English),
  4. on later runs only NEW fonts are fingerprinted (training is repeated only when the library grew by >30%).

Env: SCRIPT_URL, RAW_BASE (optional), CATALOG_FILE (testing), OUT_DIR (testing), WORKERS (4), NAUG (24), NTRAIN_AUG (30),
     MAX_TRAIN_BN (3000), MAX_TRAIN_EN (1800), EPOCHS (12), FORCE_TRAIN (0/1), TIME_BUDGET_MIN (330)
"""
import base64, hashlib, io, json, os, random, sys, time, urllib.request
from multiprocessing import Pool
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgaug
import imgfeat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_URL = os.environ.get('SCRIPT_URL', '').strip()
RAW_BASE = os.environ.get('RAW_BASE') or 'https://raw.githubusercontent.com/FoundryXorg/api/main/'
OUT_DIR = os.environ.get('OUT_DIR') or os.path.join(ROOT, 'imgindex')
WORKERS = int(os.environ.get('WORKERS', '4'))
NAUG = int(os.environ.get('NAUG', '24'))
NTRAIN_AUG = int(os.environ.get('NTRAIN_AUG', '30'))
MAX_TRAIN = {'bn': int(os.environ.get('MAX_TRAIN_BN', '3000')), 'en': int(os.environ.get('MAX_TRAIN_EN', '1800'))}
EPOCHS = int(os.environ.get('EPOCHS', '12'))
HID = (512, 192)
FORCE = os.environ.get('FORCE_TRAIN', '0') == '1'
BUDGET = float(os.environ.get('TIME_BUDGET_MIN', '330')) * 60
SCRIPT_OF = {'unicode': 'bn', 'ansi': 'ansi', 'latin': 'en'}
SPACE_OF = {'bn': 'bn', 'ansi': 'bn', 'en': 'en'}
NEED = {'bn': [0x0995, 0x09BE, 0x09AE], 'ansi': [0x41, 0x2020, 0x61], 'en': [0x41, 0x61]}
T0 = time.time()


def log(*a):
    print('[%4ds]' % (time.time() - T0), *a, flush=True)


# ---------------------------------------------------------------- catalog / fonts
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


def covered(src, script):
    from fontTools.ttLib import TTFont
    if hasattr(src, 'seek'):
        src.seek(0)
    cm = TTFont(src, fontNumber=0, lazy=True).getBestCmap() or {}
    return all(c in cm for c in NEED[script])


# ---------------------------------------------------------------- per-font sampling (runs in worker processes)
def sample_job(item):
    """returns (fid, class_key, features[n,106]) - class_key is identical for fonts that draw identical letters"""
    fid, path, script, naug = item
    try:
        src = font_source(path)
        if not covered(src, script):
            return fid, None, None
        rng = random.Random(int(hashlib.md5(fid.encode()).hexdigest()[:8], 16))
        vs = []; key = None
        for j, t in enumerate(imgaug.LIB[script]):
            g = imgaug.gray(imgaug.render_text(src, t, 80))
            if j == 0:
                key = hashlib.md5(g.tobytes() + str(g.shape).encode()).hexdigest()
            try:
                v = imgfeat.features(g)
            except Exception:
                v = None
            if v is not None:
                vs.append(v)
        nlib = len(vs)
        for _ in range(naug):
            try:
                v = imgfeat.features(imgaug.gray(imgaug.make_query(src, rng, script)))
            except Exception:
                v = None
            if v is not None:
                vs.append(v)
        if nlib < 1 or len(vs) < 4:
            return fid, None, None
        return fid, key, np.array(vs, np.float32)
    except Exception as ex:
        print('skip', fid, path, type(ex).__name__, str(ex)[:80], flush=True)
        return fid, None, None


def collect(items, naug, pool):
    out = {}
    for n, (fid, key, X) in enumerate(pool.imap_unordered(sample_job, [(a, b, c, naug) for a, b, c in items], chunksize=2), 1):
        out[fid] = (key, X)
        if n % 250 == 0:
            log('  sampled', n, '/', len(items))
    return out


# ---------------------------------------------------------------- the network
def enc(a):
    return base64.b64encode(np.asarray(a, np.float16).tobytes()).decode()


def dec(s, shape=None):
    a = np.frombuffer(base64.b64decode(s), dtype=np.float16).astype(np.float32)
    return a.reshape(shape) if shape else a


def model_from_json(m):
    return {'mean': np.array(m['mean'], np.float32), 'std': np.array(m['std'], np.float32),
            'layers': [(dec(l['W'], l['shape']), dec(l['b'])) for l in m['layers']]}


def embed(net, X):
    h = (np.asarray(X, np.float32) - net['mean']) / net['std']
    for W, b in net['layers']:
        h = np.maximum(h @ W + b, 0)
    return h


def train(space, samples, items_by_id):
    """samples: {fid: (class_key, X)} -> (model_json, report)"""
    from sklearn.neural_network import MLPClassifier
    ids = sorted(samples)
    classes = {}
    for fid in ids:
        classes.setdefault(samples[fid][0], []).append(fid)
    reps = sorted(c[0] for c in classes.values())            # one font per identical-looking group
    rng = random.Random(0); rng.shuffle(reps)
    nhold = max(20, len(reps) // 10)
    hold, tr = set(reps[:nhold]), reps[nhold:]
    log(space, 'training on', len(tr), 'fonts, validating on', len(hold), 'unseen fonts')
    X = np.concatenate([samples[f][1][:3 + NTRAIN_AUG] for f in tr]); y = np.concatenate([[i] * len(samples[f][1][:3 + NTRAIN_AUG]) for i, f in enumerate(tr)])
    mu = X.mean(0); sd = np.maximum(X.std(0), 1e-3); Xs = ((X - mu) / sd).astype(np.float32)
    m = MLPClassifier(HID, alpha=1e-3, batch_size=256, learning_rate_init=1e-3, max_iter=1, warm_start=True, random_state=0)
    for ep in range(EPOCHS):
        m.fit(Xs, y)
        if ep % 4 == 3:
            log('  epoch', ep + 1, '/', EPOCHS)
    def r16(a): return a.astype(np.float16).astype(np.float32)
    net = {'mean': mu.astype(np.float32), 'std': sd.astype(np.float32), 'layers': [(r16(W), r16(b)) for W, b in zip(m.coefs_[:-1], m.intercepts_[:-1])]}
    # honest check on fonts the network never saw during training (fingerprint from 20 samples, test with the rest)
    all_f = tr + sorted(hold)
    cut = lambda f: max(3, int(len(samples[f][1]) * 0.6))
    P = np.array([embed(net, samples[f][1][:cut(f)]).mean(0) for f in all_f]); P /= np.maximum(np.linalg.norm(P, axis=1, keepdims=True), 1e-9)
    hits = np.zeros(4); n = 0
    for f in sorted(hold):
        i = all_f.index(f); Q = embed(net, samples[f][1][cut(f):])
        if len(Q) == 0:
            continue
        Q /= np.maximum(np.linalg.norm(Q, axis=1, keepdims=True), 1e-9)
        for d in -(Q @ P.T):
            r = int((d < d[i]).sum()); n += 1
            for j, k in enumerate((1, 5, 10, 20)):
                hits[j] += r < k
    rep = {'trained_fonts': len(tr), 'validation_fonts': len(hold), 'validation_queries': n,
           'unseen_top1_top5_top10_top20': [round(float(h) / max(1, n), 3) for h in hits], 'library_size_in_test': len(all_f)}
    log(space, 'validation on unseen fonts (top1/5/10/20):', rep['unseen_top1_top5_top10_top20'])
    model = {'mean': np.round(mu, 6).tolist(), 'std': np.round(sd, 6).tolist(),
             'layers': [{'W': enc(W), 'b': enc(b), 'shape': list(W.shape)} for W, b in zip(m.coefs_[:-1], m.intercepts_[:-1])]}
    return model, rep


# ---------------------------------------------------------------- index files
def load_old(space):
    p = os.path.join(OUT_DIR, '%s.json' % space)
    if not os.path.exists(p):
        return None
    try:
        o = json.load(open(p, encoding='utf-8'))
        k = o['dim']
        q = np.frombuffer(base64.b64decode(o['q']), dtype=np.uint8).reshape(-1, k).astype(np.float32)
        vecs = q / 255.0 * np.array(o['m'], np.float32)[:, None]
        return {'model': o['model'], 'model_id': o['model_id'], 'trained_n': o.get('trained_n', 0), 'report': o.get('report'),
                'vecs': {fid: vecs[i] for i, fid in enumerate(o['ids'])}, 'bad': set(o.get('skipped', []))}
    except Exception as ex:
        log('could not read old index', space, ex)
        return None


def save(space, model, model_id, trained_n, report, vecs, bad):
    ids = sorted(vecs)
    k = HID[-1]
    M = np.array([vecs[i] for i in ids], np.float32).reshape(-1, k)
    mx = np.maximum(M.max(1), 1e-9) if len(M) else np.zeros(0)
    q = np.clip(np.round(M / mx[:, None] * 255), 0, 255).astype(np.uint8) if len(M) else np.zeros((0, k), np.uint8)
    out = {'v': 2, 'built': time.strftime('%Y-%m-%d'), 'model_id': model_id, 'trained_n': trained_n, 'dim': k, 'ids': ids,
           'm': [round(float(x), 5) for x in mx], 'q': base64.b64encode(q.tobytes()).decode(), 'skipped': sorted(bad),
           'report': report, 'model': model}
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, '%s.json' % space)
    json.dump(out, open(path, 'w', encoding='utf-8'), separators=(',', ':'))
    log('wrote', path, os.path.getsize(path), 'bytes;', len(ids), 'fonts;', len(bad), 'skipped')


def proto(net, X):
    e = embed(net, X).mean(0)
    return (e / max(np.linalg.norm(e), 1e-9)).astype(np.float32)


# ---------------------------------------------------------------- main
def main():
    fonts = [f for f in catalog() if f.get('id') and f.get('path') and str(f['path']).lower().rsplit('.', 1)[-1] in ('ttf', 'otf', 'ttc')]
    live = {str(f['id']) for f in fonts}
    by_space = {'bn': [], 'en': []}
    for f in fonts:
        script = SCRIPT_OF.get(str(f.get('encoding') or 'unicode').lower(), 'bn')
        by_space[SPACE_OF[script]].append((str(f['id']), f['path'], script))
    log('catalog', len(fonts), '| Bangla space', len(by_space['bn']), '| English space', len(by_space['en']))
    with Pool(WORKERS) as pool:
        for space in ('bn', 'en'):
            items = by_space[space]
            if not items:
                continue
            old = load_old(space)
            need_train = FORCE or old is None or len(items) > 1.3 * max(1, old['trained_n'])
            samples = {}
            if need_train:
                rng = random.Random(1); pick = items[:]; rng.shuffle(pick)
                log(space, 'TRAINING needed (', 'no model yet' if old is None else 'library grew / forced', ') - collecting samples')
                samples = collect(pick[:MAX_TRAIN[space] + 200], NTRAIN_AUG, pool)   # 3 fixed lines + NTRAIN_AUG variations
                samples = {k: v for k, v in samples.items() if v[1] is not None}
                if len(samples) < 60:
                    log(space, 'too few usable fonts to train (', len(samples), ') - skipping'); continue
                model, report = train(space, samples, None)
                model_id = hashlib.md5(json.dumps(model['mean']).encode() + model['layers'][0]['W'].encode()[:4000]).hexdigest()[:10]
                trained_n = len(items)
                vecs, bad = {}, set()
            else:
                model, model_id, trained_n, report = old['model'], old['model_id'], old['trained_n'], old['report']
                vecs = {k: v for k, v in old['vecs'].items() if k in live}; bad = {b for b in old['bad'] if b in live}
            net = model_from_json(model)
            for fid, (key, X) in samples.items():          # fonts already sampled for training: fingerprint from the same samples
                vecs[fid] = proto(net, X)
            work = [it for it in items if it[0] not in vecs and it[0] not in bad]
            log(space, 'fingerprinting', len(work), 'fonts (', len(vecs), 'already done )')
            done = 0
            for fid, key, X in pool.imap_unordered(sample_job, [(a, b, c, NAUG) for a, b, c in work], chunksize=2):
                done += 1
                if X is None:
                    bad.add(fid)
                else:
                    vecs[fid] = proto(net, X)
                if done % 250 == 0:
                    log('  fingerprinted', done, '/', len(work))
                if done % 1500 == 0:
                    save(space, model, model_id, trained_n, report, vecs, bad)
                if time.time() - T0 > BUDGET:
                    log('time budget reached - saving; the next run continues'); pool.terminate(); break
            save(space, model, model_id, trained_n, report, vecs, bad)
            if time.time() - T0 > BUDGET:
                break
    log('finished')


if __name__ == '__main__':
    main()
