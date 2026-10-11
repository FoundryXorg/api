"""Training/indexing helpers: render text with a font and make realistic 'photo of text' variations."""
import io, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

BN_LIB = ["আমার সোনার বাংলা আমি তোমায় ভালোবাসি", "বাংলাদেশের স্বাধীনতা সংগ্রামের ইতিহাস গৌরবের", "শিক্ষা ও গবেষণা কেন্দ্র ঢাকা চট্টগ্রাম"]
AN_LIB = ["Avgvi †mvbvi evsjv Avwg †Zvgvq fv‡jvevwm", "evsjv fvlv Avgvi gv‡qi fvlv", "evsjv‡`‡ki my›`i cÖK…wZ"]
EN_LIB = ["The quick brown fox jumps over the lazy dog 0123456789",
          "Sphinx of black quartz, judge my vow. Pack my box with five dozen liquor jugs",
          "Amazingly few discotheques provide jukeboxes — Grumpy wizards make toxic brew"]
BN_WORDS = "বাংলা ভাষা আমার দেশ মানুষ সমাজ শিক্ষা কবিতা নদী গ্রাম প্রকৃতি স্বাধীনতা ইতিহাস সংস্কৃতি উৎসব বই খবর ভালোবাসা সুন্দর আকাশ রাত্রি স্বপ্ন জীবন সময় পথ মাটি".split()
AN_WORDS = "evsjv fvlv Avgvi †`k gvbyl mgvR wkÿv Kwe b`x MÖvg cÖK…wZ my›`i ¯‹zj ZvwiL Lvevi eB Lei fvjevmv AvKvk ¯^cœ Rxeb mgq c_ gvwU".split()
EN_WORDS = "summer sale design studio coffee house market river garden paper window yellow mountain future music travel bakery fresh organic urban classic modern vintage family history winter spring button welcome journey signal harbor lantern marble velvet quiet rapid golden silver shadow bright orange purple forest ocean planet rocket castle bridge".split()
LIB = {'bn': BN_LIB, 'ansi': AN_LIB, 'en': EN_LIB}
WORDS = {'bn': BN_WORDS, 'ansi': AN_WORDS, 'en': EN_WORDS}


def open_font(src, size):
    try:
        return ImageFont.truetype(src, size, layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        if hasattr(src, 'seek'):
            src.seek(0)
        return ImageFont.truetype(src, size)


def render_text(src, text, size=72, fg=0, bg=255, pad=30):
    if hasattr(src, 'seek'):
        src.seek(0)
    f = open_font(src, size)
    l, t, r, b = f.getbbox(text)
    im = Image.new('RGB', (r - l + 2 * pad, b - t + 2 * pad), bg)
    ImageDraw.Draw(im).text((pad - l, pad - t), text, font=f, fill=fg)
    return im


def gray(im):
    a = np.asarray(im.convert('RGB'), dtype=np.uint32)
    return ((a[..., 0] * 19595 + a[..., 1] * 38470 + a[..., 2] * 7471 + 0x8000) >> 16).astype(np.uint8)


def make_query(src, rng, script):
    words = WORDS[script]
    text = ' '.join(rng.choice(words) for _ in range(rng.choice([1, 2, 3, 4])))
    if script == 'en':
        if rng.random() < 0.25:
            text = text.upper()
        elif rng.random() < 0.3:
            text = text.title()
    size = rng.choice([22, 30, 44, 64, 96, 140])
    dark_on_light = rng.random() < 0.7
    pal = [((20, 20, 20), (250, 250, 250)), ((10, 30, 90), (235, 235, 220)), ((120, 20, 20), (255, 245, 240)), ((40, 60, 40), (225, 235, 225))]
    fg, bg = rng.choice(pal)
    if not dark_on_light:
        fg, bg = bg, fg
    im = render_text(src, text, size, fg, bg, pad=rng.choice([6, 14, 30]))
    if rng.random() < 0.4:
        im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.1)))
    a = np.asarray(im, dtype=np.float32)
    if rng.random() < 0.5:
        a = a + np.random.default_rng(rng.randrange(10 ** 6)).normal(0, rng.uniform(2, 9), a.shape)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if rng.random() < 0.5:
        buf = io.BytesIO()
        im.save(buf, 'JPEG', quality=rng.choice([40, 60, 80, 92]))
        im = Image.open(io.BytesIO(buf.getvalue()))
    if rng.random() < 0.3:
        s = rng.uniform(0.5, 1.8)
        im = im.resize((max(8, int(im.width * s)), max(8, int(im.height * s))), Image.BILINEAR)
    return im
