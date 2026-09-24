"""Montage « référence » (v4) : visage plein écran, sous-titres blancs sur la vidéo, cartes beige,
fonds photo (chambre 3D photoréaliste), carte sombre masterclass.

Usage : python3 composite_ref.py <src.mp4> <dossier_3d> [images_de_test]
Écrit des images RGB brutes 1080x1920 sur stdout (à piper dans ffmpeg).

Principe : la vidéo d'origine contient déjà des sous-titres, un logo et des bandeaux incrustés.
- Pendant les bandeaux, on affiche des cartes plein écran (la voix continue).
- Sur les plans visage, les anciens sous-titres et la barre de progression sont effacés (inpainting),
  le logo sort du cadre grâce à un léger zoom, et les nouveaux sous-titres blancs se posent par-dessus.
"""
import sys, os, glob, json, math
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from composite import KEEP, src_to_out, out_to_src, SHOT_CUTS

W, H, FPS = 1080, 1920, 30
FONTS = os.path.join(ROOT, 'assets', 'fonts')

# ------------------------------------------------------------------ palette
def hexrgb(h): h = h.lstrip('#'); return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
BG, BG2 = hexrgb('#F2F1EC'), hexrgb('#E8E6DF')
INK, MUTED, SAGE = hexrgb('#1E2420'), hexrgb('#8B9089'), hexrgb('#4F7D63')
DARK, DARK2, CREAM, SAGE_L = hexrgb('#1F2522'), hexrgb('#2A312D'), hexrgb('#F2F1EC'), hexrgb('#9DC6AE')
LINE = hexrgb('#D5D3CB')

# ------------------------------------------------------------------ timing (temps source -> sortie)
VOICE_END = 35.0
END_HOLD = 2.8
T_END = src_to_out(VOICE_END)
DUR = T_END + END_HOLD
NFR = int(DUR * FPS)
o = src_to_out

# (type, début source, fin source) — les fins de bandeaux d'origine sont couvertes avec une marge
SCENES = [
    ('face_hook', 0.00, 0.95),
    ('contrats', 0.95, 4.45),
    ('equipe', 4.45, 8.25),
    ('chaine', 8.25, 12.30),
    ('conciergerie', 12.30, 16.45),
    ('chambre', 16.45, 19.10),
    ('commission', 19.10, 23.40),
    ('face_clic', 23.40, 25.20),
    ('masterclass', 25.20, 31.75),
    ('face_resultats', 31.75, VOICE_END),
    ('fin', VOICE_END, None),
]
TRANS = 0.30   # durée des transitions entre scènes (s)

# ------------------------------------------------------------------ utilitaires
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease_out(x): x = clamp(x); return 1 - (1 - x) ** 3
def ease_in_out(x): x = clamp(x); return x * x * (3 - 2 * x)
def ease_out_back(x, s=1.6): x = clamp(x); return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2

def appear(t, t0, dur=0.45):
    """Apparition « fondu + montée » : renvoie (opacité, décalage vertical)."""
    k = ease_out((t - t0) / dur)
    return k, 26 * (1 - k)

_fonts = {}
def font(weight, size):
    k = (weight, size)
    if k not in _fonts: _fonts[k] = ImageFont.truetype(os.path.join(FONTS, 'Manrope-%d.ttf' % weight), size)
    return _fonts[k]

_txt = {}
def text_img(parts, weight, size, tracking=0):
    """parts = [(texte, couleur), …] -> image RGBA float (couleur non prémultipliée) et largeur."""
    key = (tuple(parts), weight, size, tracking)
    if key in _txt: return _txt[key]
    f = font(weight, size)
    asc, desc = f.getmetrics()
    total = 0
    for s, _ in parts:
        total += (f.getlength(s) + tracking * len(s))
    w, h = int(total + 8), asc + desc + 8
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    x = 2
    for s, col in parts:
        c = tuple(int(v * 255) for v in col) + (255,)
        if tracking:
            for ch in s:
                d.text((x, 2), ch, font=f, fill=c); x += f.getlength(ch) + tracking
        else:
            d.text((x, 2), s, font=f, fill=c); x += f.getlength(s)
    a = np.asarray(im).astype(np.float32) / 255
    _txt[key] = a
    return a

def blit(dst, rgba, x, y, op=1.0):
    h, w = rgba.shape[:2]; x, y = int(round(x)), int(round(y))
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0 or op <= 0.001: return
    s = rgba[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4] * op
    dst[y0:y1, x0:x1] = dst[y0:y1, x0:x1] * (1 - a) + s[..., :3] * a

def put_text(dst, parts, weight, size, x, y, op=1.0, align='left', tracking=0):
    im = text_img(tuple(parts), weight, size, tracking)
    if align == 'center': x -= im.shape[1] / 2
    elif align == 'right': x -= im.shape[1]
    blit(dst, im, x, y, op)
    return im.shape[1]

def rrect_mask(w, h, r, aa=2):
    m = np.zeros((h * aa, w * aa), np.uint8)
    R = r * aa
    cv2.rectangle(m, (R, 0), (w * aa - R, h * aa), 255, -1); cv2.rectangle(m, (0, R), (w * aa, h * aa - R), 255, -1)
    for cx, cy in ((R, R), (w * aa - R, R), (R, h * aa - R), (w * aa - R, h * aa - R)):
        cv2.circle(m, (cx, cy), R, 255, -1, cv2.LINE_AA)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255

_shadow = {}
def soft_shadow(dst, x, y, w, h, r, strength=0.18, blur=28, dy=18):
    key = (w, h, r, blur)
    if key not in _shadow:
        pad = blur * 3
        m = np.zeros((h + 2 * pad, w + 2 * pad), np.float32)
        m[pad:pad + h, pad:pad + w] = rrect_mask(w, h, r)
        _shadow[key] = (cv2.GaussianBlur(m, (0, 0), blur), pad)
    m, pad = _shadow[key]
    rgba = np.zeros(m.shape + (4,), np.float32); rgba[..., 3] = m * strength
    blit(dst, rgba, x - pad, y - pad + dy)

def fill_rrect(dst, x, y, w, h, r, col, op=1.0):
    m = rrect_mask(int(w), int(h), int(r))
    rgba = np.zeros(m.shape + (4,), np.float32); rgba[..., :3] = col; rgba[..., 3] = m
    blit(dst, rgba, x, y, op)

def check_icon(dst, cx, cy, r, bg, fg, op=1.0, k=1.0):
    """Pastille ronde avec coche dessinée (k = progression du tracé)."""
    s = int(r * 2 + 6); m = np.zeros((s * 2, s * 2), np.uint8)
    cv2.circle(m, (s, s), int(r * 2), 255, -1, cv2.LINE_AA)
    disc = cv2.resize(m, (s, s), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    ck = np.zeros((s * 2, s * 2), np.uint8)
    p0, p1, p2 = (s - r * 0.9, s + r * 0.05), (s - r * 0.25, s + r * 0.65), (s + r * 0.95, s - r * 0.6)
    pts = [p0, p1, p2]; L1 = math.dist(p0, p1); L2 = math.dist(p1, p2); tot = (L1 + L2) * k
    th = max(2, int(r * 0.42))
    if tot > 0:
        e = min(tot, L1) / L1
        cv2.line(ck, tuple(int(v) for v in p0), tuple(int(p0[i] + (p1[i] - p0[i]) * e) for i in (0, 1)), 255, th, cv2.LINE_AA)
        if tot > L1:
            e = (tot - L1) / L2
            cv2.line(ck, tuple(int(v) for v in p1), tuple(int(p1[i] + (p2[i] - p1[i]) * e) for i in (0, 1)), 255, th, cv2.LINE_AA)
    ck = cv2.resize(ck, (s, s), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    rgba = np.zeros((s, s, 4), np.float32)
    rgba[..., :3] = np.asarray(bg) * (1 - ck[..., None]) + np.asarray(fg) * ck[..., None]
    rgba[..., 3] = disc
    blit(dst, rgba, cx - s / 2, cy - s / 2, op)

def background(dark=False):
    top, bot = (DARK, DARK2) if dark else (BG, BG2)
    g = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    return np.broadcast_to(np.asarray(top, np.float32) * (1 - g) + np.asarray(bot, np.float32) * g, (H, W, 3)).copy()
BG_LIGHT = background(False); BG_DARK = background(True)

def label(img, t, t0, s, dark=False):
    op, dy = appear(t, t0)
    col = (0.62, 0.66, 0.63) if dark else MUTED
    # petit trait qui se dessine + texte en capitales espacées
    L = int(46 * ease_out((t - t0) / 0.5))
    if L > 1: img[167 + int(dy):170 + int(dy), 80:80 + L] = np.asarray(col) * op + img[167 + int(dy):170 + int(dy), 80:80 + L] * (1 - op)
    put_text(img, [(s, col)], 700, 26, 142, 150 + dy, op, tracking=3)

def title(img, t, t0, lines, y=205, size=86, dark=False):
    """lines = [[(texte, couleur), …], …] ; chaque ligne apparaît avec un léger décalage."""
    for i, parts in enumerate(lines):
        op, dy = appear(t, t0 + 0.09 * i)
        put_text(img, parts, 800, size, 76, y + i * size * 1.12 + dy, op)

# ------------------------------------------------------------------ éléments 3D (séquences PNG)
class Seq:
    def __init__(self, folder):
        self.files = sorted(glob.glob(os.path.join(folder, '*.png')))
        self.cache = {}
    def get(self, i, width):
        i = int(clamp(i, 0, len(self.files) - 1))
        k = (i, width)
        if k not in self.cache:
            im = cv2.imread(self.files[i], cv2.IMREAD_UNCHANGED).astype(np.float32) / 255
            im = cv2.resize(im, (width, int(im.shape[0] * width / im.shape[1])), interpolation=cv2.INTER_AREA)
            im[..., :3] = im[..., 2::-1][..., :3]     # BGR -> RGB
            self.cache = {kk: v for kk, v in self.cache.items() if kk[0] >= i - 2}
            self.cache[k] = im
        return self.cache[k]
    def draw(self, img, t, t0, x, y, width, op=1.0):
        if not self.files: return
        im = self.get((t - t0) * FPS, width)
        # ombre douce posée « au sol » : alpha flouté, légèrement écrasé et décalé vers le bas
        a = im[..., 3]
        sh = cv2.resize(a, (a.shape[1], int(a.shape[0] * 0.92)))
        pad = 60
        m = np.zeros((a.shape[0] + 2 * pad, a.shape[1] + 2 * pad), np.float32)
        m[pad + a.shape[0] - sh.shape[0]:pad + a.shape[0], pad:pad + a.shape[1]] = sh
        m = cv2.GaussianBlur(m, (0, 0), 16) * 0.20
        rgba = np.zeros(m.shape + (4,), np.float32); rgba[..., 3] = m
        blit(img, rgba, x - pad, y - pad + 24, op)
        blit(img, im, x, y, op)

# ------------------------------------------------------------------ sous-titres
KEYWORDS = ['propriétaires', 'signés', 'conciergerie', 'Pierre', 'père', 'accompagnement', 'ans', '1500', 'YouTube',
            'quoi', 'accompagner', 'courte', 'durée', 'commissions', '25', 'cliquer', 'Masterclass', 'gratuite',
            'exactement', 'fonctionner', 'garantir', 'résultats', 'lancement', 'mois', '10', '4', '3', '6', '20']

def build_chunks(words):
    toks = []
    for a, b, w in words:
        if toks and not w.startswith(' ') and w not in ('%',):
            toks[-1][2] += w; toks[-1][1] = b          # « c » + « 'est »
        elif w == '%' and toks:
            toks[-1][2] += '%'; toks[-1][1] = b
        else:
            toks.append([a, b, w.strip()])
    for t in toks:
        t[2] = t[2].replace('AirBnb', 'Airbnb').replace('1500', '1 500').replace('Youtube', 'YouTube')
    chunks, cur = [], []
    for tk in toks:
        cur.append(tk)
        txt = ' '.join(x[2] for x in cur)
        end_sentence = tk[2].endswith(('.', '?', ','))
        if len(cur) >= 4 or len(txt) > 20 or end_sentence:
            chunks.append(cur); cur = []
    if cur: chunks.append(cur)
    out = []
    for i, c in enumerate(chunks):
        start = c[0][0]; end = chunks[i + 1][0][0] if i + 1 < len(chunks) else c[-1][1] + 0.3
        end = min(end, c[-1][1] + 0.6)
        words_ = [x[2].rstrip('.,') if j == len(c) - 1 and x[2].endswith(('.', ',')) else x[2] for j, x in enumerate(c)]
        hl = -1
        for kw in KEYWORDS:
            for j, w in enumerate(words_):
                if kw.lower() in w.lower().replace(' ', '').replace('%', ''):
                    hl = j; break
            if hl >= 0: break
        out.append((start, end, words_, hl))
    return out

_subsh = {}
def subtitles_video(img, ts, chunks, y=1545):
    """Sous-titres blancs sur la vidéo (ombre douce), mot-clé en vert clair."""
    for (a, b_, words_, hl) in chunks:
        if a - 0.02 <= ts < b_:
            k = ease_out(clamp((ts - a) / 0.12))
            parts = tuple((w + (' ' if j < len(words_) - 1 else ''), SAGE_L if j == hl else (1.0, 1.0, 1.0)) for j, w in enumerate(words_))
            im = text_img(parts, 800, 62)
            key = parts
            if key not in _subsh:
                pad = 30
                a_ = np.pad(im[..., 3], pad)
                sh = cv2.GaussianBlur(a_, (0, 0), 9) * 0.55
                rg = np.zeros(sh.shape + (4,), np.float32); rg[..., 3] = sh
                _subsh[key] = (rg, pad)
            rg, pad = _subsh[key]
            x = W / 2 - im.shape[1] / 2; yy_ = y + (1 - k) * 12
            blit(img, rg, x - pad, yy_ - pad + 4, k)
            blit(img, im, x, yy_, k)

def subtitles(img, ts, chunks, dark=False, y=1500):
    for (a, b, words_, hl) in chunks:
        if a - 0.02 <= ts < b:
            k = clamp((ts - a) / 0.12)
            base = CREAM if dark else INK
            acc = SAGE_L if dark else SAGE
            parts = []
            for j, w in enumerate(words_):
                parts.append((w + (' ' if j < len(words_) - 1 else ''), acc if j == hl else base))
            im = text_img(tuple(parts), 800, 58)
            sc = 0.94 + 0.06 * ease_out(k)
            if sc < 0.999:
                im = cv2.resize(im, (int(im.shape[1] * sc), int(im.shape[0] * sc)), interpolation=cv2.INTER_AREA)
            blit(img, im, W / 2 - im.shape[1] / 2, y + (1 - ease_out(k)) * 10, ease_out(k))

# ------------------------------------------------------------------ plan visage
WIN_X, WIN_Y, WIN_W, WIN_H, WIN_R = 60, 250, 960, 1100, 40
WIN_MASK = rrect_mask(WIN_W, WIN_H, WIN_R)[..., None]
CROP_BOTTOM = 650            # anciens sous-titres à partir de y = 658 (sur 848)

def shot_start(ts):
    cuts = sorted(SHOT_CUTS + [b for a, b in KEEP[:-1]])
    prev = 0.0; idx = 0
    for c in cuts:
        if ts >= c: prev = c; idx += 1
    return prev, idx

def face_window(frames, ts, top=100):
    f = frames[min(len(frames) - 1, int(round(ts * 30)))]
    h = CROP_BOTTOM - top; w = h * WIN_W / WIN_H
    start, idx = shot_start(ts)
    z = 1.0 + (0.035 if idx % 2 else 0.0) + 0.03 * ease_in_out((ts - start) / 4)
    cx, cy = 226, top + h * 0.55
    ww, hh = w / z, h / z
    x0 = clamp(cx - ww / 2, 0, 480 - ww); y0 = clamp(cy - hh * 0.55, top, CROP_BOTTOM - hh)
    M = np.array([[ww / WIN_W, 0, x0], [0, hh / WIN_H, y0]], np.float64)
    im = cv2.warpAffine(f, M, (WIN_W, WIN_H), flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)
    im = im[..., ::-1].astype(np.float32) / 255
    bl = cv2.GaussianBlur(im, (0, 0), 1.4)
    im = np.clip(im + (im - bl) * 0.6, 0, 1)
    # étalonnage doux, légèrement chaud et désaturé pour se marier au beige
    lum = im @ np.array([0.299, 0.587, 0.114], np.float32)
    im = lum[..., None] + (im - lum[..., None]) * 0.92
    im = np.clip((im - 0.5) * 1.06 + 0.5 + np.array([0.012, 0.004, -0.012], np.float32), 0, 1)
    return im

_inp = {}
def clean_frame(frames, si):
    """Efface les anciens sous-titres (boîte bleu marine) et la barre de progression par inpainting."""
    if si in _inp: return _inp[si]
    f = frames[si]
    reg = f.astype(np.int16); b, g, r = reg[..., 0], reg[..., 1], reg[..., 2]
    m = ((b > 45) & (b < 110) & (r < 60) & (g < 75) & (b > r + 15)).astype(np.uint8)
    m[:600] = 0; m[790:] = 0
    mask = np.zeros(f.shape[:2], np.uint8)
    rows = np.nonzero(m.mean(1) > 0.15)[0]
    if len(rows):
        cols = np.nonzero(m[rows.min():rows.max() + 1].mean(0) > 0.2)[0]
        if len(cols): mask[max(0, rows.min() - 5):rows.max() + 6, max(0, cols.min() - 5):cols.max() + 6] = 255
    mask[778:802, 10:470] = 255
    out = cv2.inpaint(f, mask, 7, cv2.INPAINT_TELEA)
    # adoucit la zone reconstruite (fondu progressif) pour qu'aucune trace nette ne reste
    soft = cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), 9)[..., None]
    out = (out * (1 - soft) + cv2.GaussianBlur(out, (0, 0), 7) * soft).astype(np.uint8)
    if len(_inp) > 90: _inp.clear()
    _inp[si] = out
    return out

S0 = H / 848
BOTTOM_SHADE = np.clip((np.arange(H, dtype=np.float32) - 1100) / 820, 0, 1)[:, None, None] ** 1.1 * 0.68

def draw_face(img, frames, t, ts, zoom=1.18):
    si = min(len(frames) - 1, int(round(ts * 30)))
    f = clean_frame(frames, si)
    start, idx = shot_start(ts)
    z = zoom + (0.04 if idx % 2 else 0.0) + 0.035 * ease_in_out((ts - start) / 4)
    s = S0 * z
    # sortie p -> source q = A + (p - P) / s   (ancrage sous le visage, pour garder le haut hors du logo)
    A = np.array([226.0, 636.0]); P = np.array([W / 2, H * 0.75])
    M = np.array([[1 / s, 0, A[0] - P[0] / s], [0, 1 / s, A[1] - P[1] / s]], np.float64)
    im = cv2.warpAffine(f, M, (W, H), flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)
    im = im[..., ::-1].astype(np.float32) / 255
    bl = cv2.GaussianBlur(im, (0, 0), 1.6)
    im = np.clip(im + (im - bl) * 0.6, 0, 1)
    lum = im @ np.array([0.299, 0.587, 0.114], np.float32)
    im = lum[..., None] + (im - lum[..., None]) * 0.93
    im = np.clip((im - 0.5) * 1.07 + 0.5 + np.array([0.012, 0.004, -0.010], np.float32), 0, 1)
    img[:] = im * (1 - BOTTOM_SHADE)

# ------------------------------------------------------------------ cartes
def card_contrats(img, t, E):
    t0 = o(0.95)
    label(img, t, t0, 'LE LANCEMENT')
    title(img, t, t0 + 0.05, [[('3 propriétaires.', INK)]])
    op, dy = appear(t, o(1.95))
    put_text(img, [('signés en 6 mois', SAGE)], 800, 60, 78, 312 + dy, op)
    E['contracts'].draw(img, t, t0, -30, 400, 1140)
    # frise des 6 mois
    y = 1330; x0, x1 = 130, 950
    k = ease_in_out((t - o(2.6)) / 1.5)
    img[y - 2:y + 2, x0:x1] = np.asarray(LINE)
    xe = int(x0 + (x1 - x0) * k)
    if xe > x0: img[y - 2:y + 2, x0:xe] = np.asarray(SAGE)
    for i in range(6):
        cx = x0 + (x1 - x0) * i / 5
        on = k * 5 >= i - 0.01 and t >= o(2.6)
        col = SAGE if on else LINE
        cv2.circle(img, (int(cx), y), 11, tuple(float(c) for c in col), -1, cv2.LINE_AA)
        put_text(img, [('M%d' % (i + 1), SAGE if on else MUTED)], 700, 24, cx, y + 26, 1.0, 'center')

def card_equipe(img, t, E):
    t0 = o(4.45)
    label(img, t, t0, "L'ÉQUIPE")
    title(img, t, t0 + 0.05, [[('Pierre', INK)], [('& son père.', MUTED)]])
    rows = [(o(6.05), '4 ans', 'à travailler ensemble'), (o(7.2), '+10 ans', "d'accompagnement en conciergerie")]
    for i, (tr, big, small) in enumerate(rows):
        y = 640 + i * 300
        op, dy = appear(t, tr)
        L = int((W - 160) * ease_out((t - tr + 0.1) / 0.6))
        if L > 0: img[y - 30:y - 28, 80:80 + L] = np.asarray(LINE)
        put_text(img, [(big, SAGE)], 800, 150, 74, y + dy, op)
        put_text(img, [(small, INK)], 600, 38, 80, y + 190 + dy, op)

YT_ROUGE = (1.0, 0.0, 0.2)

def yt_logo(img, x, y, h, op=1.0):
    """Petit logo lecture YouTube (rectangle rouge arrondi + triangle blanc)."""
    w = int(h * 1.42)
    fill_rrect(img, x, y, w, h, int(h * 0.28), YT_ROUGE, op)
    cx, cy = x + w / 2 + h * 0.04, y + h / 2
    lay = img.copy()
    tri = np.array([[cx - h * 0.17, cy - h * 0.21], [cx - h * 0.17, cy + h * 0.21], [cx + h * 0.22, cy]], np.int32)
    cv2.fillPoly(lay, [tri], (1.0, 1.0, 1.0), cv2.LINE_AA)
    img[:] = img * (1 - op) + lay * op
    return w

def rounded_img(im, r):
    return np.concatenate([im, rrect_mask(im.shape[1], im.shape[0], r)[..., None]], 2)

def card_chaine(img, t, E, YT):
    """Carte « chaîne YouTube de Sébastien MORE » : profil, 10 ans → 1 500 vidéos, vraies miniatures."""
    t0 = o(8.25)
    label(img, t, t0, 'LA CHAÎNE YOUTUBE')
    # en-tête profil
    op, dy = appear(t, t0 + 0.08)
    ax, ay, ar = 80, 212 + dy, 46
    av = YT['avatar_rond']
    blit(img, av, ax, ay, op)
    put_text(img, [(YT['nom'], INK)], 800, 40, ax + 2 * ar + 22, ay + 4, op)
    put_text(img, [(YT['handle'], MUTED)], 600, 28, ax + 2 * ar + 22, ay + 54, op)
    lw = yt_logo(img, W - 80 - 62, ay + 22, 44, op)
    # titre : « 10 ans d'accompagnement. » puis « 1 500 vidéos. »
    swap = o(10.25)
    if t < swap:
        if t >= o(9.1):
            title(img, t, o(9.1), [[('10 ans', SAGE)], [("d'accompagnement.", INK)]], y=345)
    else:
        k = ease_out((t - swap) / (o(10.8) - swap))
        n = int(round(1500 * k / 10) * 10)
        title(img, t, swap, [[('{:,}'.format(n).replace(',', ' '), SAGE), (' vidéos.', INK)]], y=345)
        op2, dy2 = appear(t, o(10.9))
        put_text(img, [(YT['abonnes'], MUTED)], 700, 38, 80, 455 + dy2, op2)
    # grande miniature « à la une » qui change + deux bandes qui défilent
    thumbs_big, thumbs_small = YT['grandes'], YT['petites']
    op3, dy3 = appear(t, t0 + 0.25, 0.6)
    fw, fh, fx, fy = 920, 518, 80, 540
    per = 0.95
    j = int(max(0.0, t - t0 - 0.25) / per)
    frac = (max(0.0, t - t0 - 0.25) % per) / per
    cur = thumbs_big[j % len(thumbs_big)]; nxt = thumbs_big[(j + 1) % len(thumbs_big)]
    kz = 1.0 + 0.04 * frac
    def kb(im):
        h_, w_ = im.shape[:2]; cw, ch = int(w_ / kz), int(h_ / kz)
        x0, y0 = (w_ - cw) // 2, (h_ - ch) // 2
        return cv2.resize(im[y0:y0 + ch, x0:x0 + cw], (fw, fh), interpolation=cv2.INTER_AREA)
    feat = kb(cur)
    if frac > 0.82:
        a_ = ease_in_out((frac - 0.82) / 0.18)
        feat = feat * (1 - a_) + cv2.resize(nxt, (fw, fh), interpolation=cv2.INTER_AREA) * a_
    soft_shadow(img, fx, fy + dy3, fw, fh, 26, 0.28 * op3, 26, 20)
    blit(img, rounded_img(feat.astype(np.float32), 26), fx, fy + dy3, op3)
    # badge lecture au centre de la miniature
    lay = img.copy(); cx, cy = fx + fw / 2, fy + dy3 + fh / 2
    fill_rrect(lay, cx - 48, cy - 34, 96, 68, 18, YT_ROUGE, 0.92)
    tri = np.array([[cx - 12, cy - 16], [cx - 12, cy + 16], [cx + 18, cy]], np.int32)
    cv2.fillPoly(lay, [tri], (1.0, 1.0, 1.0), cv2.LINE_AA)
    img[:] = img * (1 - op3) + lay * op3
    # deux rangées de petites miniatures qui défilent en sens opposé
    tw, th_, gap = 280, 158, 18
    for row in range(2):
        yb = 1098 + row * (th_ + gap)
        op4, dy4 = appear(t, t0 + 0.35 + 0.1 * row, 0.6)
        speed = 70 if row == 0 else -70
        off = ((t - t0) * speed) % (tw + gap)
        seq = thumbs_small[row::2]
        for i in range(-1, 5):
            x = 80 + i * (tw + gap) - off if speed > 0 else 80 + i * (tw + gap) + off - (tw + gap)
            im = seq[(i + 20) % len(seq)]
            blit(img, im, x, yb + dy4, op4)

def card_conciergerie(img, t, E):
    t0 = o(12.30)
    label(img, t, t0, 'LA CONCIERGERIE')
    swap = o(14.35)
    if t < swap:
        title(img, t, t0 + 0.05, [[("C'est quoi ?", INK)]])
    else:
        title(img, t, swap, [[('Accompagner', INK)], [('des propriétaires.', SAGE)]])
    E['house'].draw(img, t, o(12.45), 80, 470, 920)

def card_commission(img, t, E):
    t0 = o(19.10)
    label(img, t, t0, 'LE MODÈLE ÉCONOMIQUE')
    title(img, t, t0 + 0.05, [[('En échange.', INK)]])
    k1 = ease_out((t - o(20.55)) / 0.5); k2 = ease_out((t - o(20.95)) / 0.5)
    if t >= o(20.55):
        a = int(round(20 * k1)); b = int(round(25 * k2)) if t >= o(20.95) else None
        parts = [('%d' % a, SAGE)] + ([(' à %d %%' % b, SAGE)] if b is not None else [(' %', SAGE)])
        op, dy = appear(t, o(20.55))
        put_text(img, parts, 800, 120, 74, 300 + dy, op)
    op, dy = appear(t, o(21.9))
    put_text(img, [('de commission sur le revenu locatif', MUTED)], 600, 36, 80, 450 + dy, op)
    E['split'].draw(img, t, o(19.25), 170, 540, 740)
    # légende
    op, dy = appear(t, o(21.5))
    for i, (col, txt) in enumerate(((CREAM, 'Revenu locatif'), (SAGE, 'Ta commission'))):
        x = 190 + i * 380; y = 1390 + dy
        fill_rrect(img, x, y, 34, 34, 8, col, op)
        if i == 0:
            fill_rrect(img, x, y, 34, 34, 8, LINE, op * 0.6); fill_rrect(img, x + 3, y + 3, 28, 28, 6, (1, 1, 1), op)
        put_text(img, [(txt, INK)], 700, 32, x + 50, y - 6, op)

MC_IMG = None
def card_masterclass(img, t, E):
    global MC_IMG
    t0 = o(25.20)
    label(img, t, t0, 'MASTERCLASS GRATUITE', dark=True)
    title(img, t, t0 + 0.05, [[('Une masterclass', CREAM)]], dark=True)
    op, dy = appear(t, o(28.1))
    put_text(img, [('100 % gratuite.', SAGE_L)], 800, 86, 76, 301 + dy, op)
    # visuel de la masterclass (tiré de l'écran de fin d'origine), cadre arrondi + légère dérive
    op, dy = appear(t, t0 + 0.2, 0.6)
    w, h = 940, 610
    if MC_IMG is None:
        im = cv2.imread(os.path.join(ROOT, 'assets', 'images', 'masterclass_img.png'))[..., ::-1]
        im = cv2.resize(im, (int(w * 1.08), int(h * 1.08)), interpolation=cv2.INTER_LANCZOS4).astype(np.float32) / 255
        bl = cv2.GaussianBlur(im, (0, 0), 1.5); MC_IMG = np.clip(im + (im - bl) * 0.5, 0, 1)
    drift = clamp((t - t0) / (o(31.75) - t0))
    ox = int((MC_IMG.shape[1] - w) * drift); oy = int((MC_IMG.shape[0] - h) * 0.5)
    crop = MC_IMG[oy:oy + h, ox:ox + w]
    rgba = np.concatenate([crop, rrect_mask(w, h, 28)[..., None]], 2)
    soft_shadow(img, 70, 470 + dy, w, h, 28, 0.35 * op, 30, 22)
    blit(img, rgba, 70, 470 + dy, op)
    items = [(o(29.85), "Comment fonctionne l'activité"), (o(30.45), 'Comment lancer ta conciergerie'), (o(31.05), 'Comment obtenir des résultats')]
    for i, (tt, s) in enumerate(items):
        op, dy = appear(t, tt, 0.4)
        y = 1130 + i * 92 + dy
        check_icon(img, 104, y + 26, 24, SAGE, CREAM, op, clamp((t - tt - 0.1) / 0.3))
        put_text(img, [(s, CREAM)], 700, 38, 150, y, op)

CHAMBRE = None
def chambre_bg(img, t, t0, dur, zoom0=1.0, zoom1=1.07):
    """Photo de chambre (rendu 3D) avec lent mouvement de caméra (Ken Burns)."""
    global CHAMBRE
    if CHAMBRE is None:
        CHAMBRE = cv2.imread(os.path.join(ROOT, 'assets', 'images', 'chambre.png'))[..., ::-1].astype(np.float32) / 255
    k = ease_in_out((t - t0) / dur)
    z = zoom0 + (zoom1 - zoom0) * k
    M = cv2.getRotationMatrix2D((W * 0.5, H * 0.62), 0, z)
    M[1, 2] += -30 * k
    img[:] = cv2.warpAffine(CHAMBRE, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    # voile clair en haut pour la lisibilité du titre
    g = np.clip(1 - np.arange(H, dtype=np.float32) / 620, 0, 1)[:, None, None] ** 1.5 * 0.55
    img[:] = img * (1 - g) + np.asarray(BG, np.float32) * g

def card_chambre(img, t, E):
    t0 = o(16.45)
    chambre_bg(img, t, t0, o(19.10) - t0 + TRANS)
    label(img, t, t0 + 0.05, 'LOCATION COURTE DURÉE')
    title(img, t, t0 + 0.1, [[('Location', INK)], [('courte durée.', SAGE)]])

def card_fin(img, t, E):
    t0 = T_END
    chambre_bg(img, t, t0, END_HOLD + 0.5, 1.04, 1.12)
    op, dy = appear(t, t0 + 0.05)
    im = text_img((('MASTERCLASS GRATUITE', CREAM),), 700, 24, 3)
    fill_rrect(img, 76, 140 + dy, im.shape[1] + 44, 52, 26, INK, op)
    blit(img, im, 98, 150 + dy, op)
    title(img, t, t0 + 0.12, [[('Ta conciergerie.', INK)], [('Lance-toi.', SAGE)]], y=230)
    # bouton
    op3, dy3 = appear(t, t0 + 0.45)
    pulse = 1 + 0.02 * math.sin((t - t0) * 5) * clamp((t - t0 - 0.8) / 0.3)
    bw, bh = int(620 * pulse), int(104 * pulse)
    bx, by = 76, 470 + dy3 - (bh - 104) / 2
    soft_shadow(img, bx, by, bw, bh, 52, 0.22 * op3, 20, 14)
    fill_rrect(img, bx, by, bw, bh, 52, INK, op3)
    nudge = 8 * max(0, math.sin((t - t0) * 4)) * clamp((t - t0 - 0.8) / 0.3)
    put_text(img, [('VOIR LA MASTERCLASS', CREAM)], 800, 32, bx + 44, by + bh / 2 - 24, op3, 'left', 2)
    ax, ay = int(bx + bw - 60 + nudge), int(by + bh / 2)
    lay = img.copy(); col = tuple(float(v) for v in SAGE_L)
    cv2.line(lay, (ax - 20, ay), (ax + 18, ay), col, 5, cv2.LINE_AA)
    cv2.line(lay, (ax + 4, ay - 14), (ax + 19, ay), col, 5, cv2.LINE_AA)
    cv2.line(lay, (ax + 4, ay + 14), (ax + 19, ay), col, 5, cv2.LINE_AA)
    img[:] = img * (1 - op3) + lay * op3
    op4, dy4 = appear(t, t0 + 0.7)
    put_text(img, [('100 % gratuite · clique autour de la vidéo', INK)], 600, 30, 80, 600 + dy4, op4)

# ------------------------------------------------------------------ rendu d'une scène
def render_scene(sc, t, frames, E, chunks, thumbs):
    kind, a, b = sc
    ts = out_to_src(min(t, T_END - 1e-3))
    dark = kind == 'masterclass'
    img = (BG_DARK if dark else BG_LIGHT).copy()
    t0 = o(a)
    if kind == 'face_hook':
        draw_face(img, frames, t, ts, zoom=1.42)
    elif kind.startswith('face_'):
        draw_face(img, frames, t, ts)
    elif kind == 'chambre': card_chambre(img, t, E)
    elif kind == 'contrats': card_contrats(img, t, E)
    elif kind == 'equipe': card_equipe(img, t, E)
    elif kind == 'chaine': card_chaine(img, t, E, thumbs)
    elif kind == 'conciergerie': card_conciergerie(img, t, E)
    elif kind == 'commission': card_commission(img, t, E)
    elif kind == 'masterclass': card_masterclass(img, t, E)
    elif kind == 'fin': card_fin(img, t, E)
    if kind.startswith('face_') and t < T_END:
        subtitles_video(img, ts, chunks)
    elif kind != 'fin' and t < T_END:
        subtitles(img, ts, chunks, dark)
    if kind not in ('fin', 'chambre') and not kind.startswith('face_'):
        put_text(img, [('locationcourteduree.fr', (0.55, 0.58, 0.55) if dark else MUTED)], 600, 26, W / 2, 1810, 0.9, 'center', 1)
    return img

def load_chaine():
    """Charge assets/youtube : chaine.json, avatar.jpg, thumbs/*.jpg (miniatures réelles de la chaîne)."""
    d = os.path.join(ROOT, 'assets', 'youtube')
    info = json.load(open(os.path.join(d, 'chaine.json'), encoding='utf-8'))
    av = cv2.imread(os.path.join(d, 'avatar.jpg'))[..., ::-1].astype(np.float32) / 255
    side = min(av.shape[:2]); av = av[(av.shape[0] - side) // 2:(av.shape[0] + side) // 2, (av.shape[1] - side) // 2:(av.shape[1] + side) // 2]
    av = cv2.resize(av, (92, 92), interpolation=cv2.INTER_AREA)
    m = np.zeros((368, 368), np.uint8); cv2.circle(m, (184, 184), 184, 255, -1, cv2.LINE_AA)
    m = cv2.resize(m, (92, 92), interpolation=cv2.INTER_AREA).astype(np.float32)[..., None] / 255
    grandes, petites = [], []
    for f in info['miniatures']:
        im = cv2.imread(os.path.join(d, 'thumbs', f))
        if im is None: continue
        im = im[..., ::-1].astype(np.float32) / 255
        grandes.append(cv2.resize(im, (1000, 563), interpolation=cv2.INTER_AREA))
        sm = cv2.resize(im, (280, 158), interpolation=cv2.INTER_AREA)
        petites.append(np.concatenate([sm, rrect_mask(280, 158, 14)[..., None]], 2))
    return dict(nom=info['nom'], handle=info['handle'], abonnes=info['abonnes'],
                avatar_rond=np.concatenate([av, m], 2), grandes=grandes[:info.get('nb_une', 5)], petites=petites)

def main():
    src, d3 = sys.argv[1], sys.argv[2]
    only = [int(v) for v in sys.argv[3].split(',')] if len(sys.argv) > 3 else None
    cap = cv2.VideoCapture(src); frames = []
    while True:
        ok, f = cap.read()
        if not ok: break
        frames.append(f)
    words = json.load(open(os.path.join(os.path.dirname(src), 'words.json')))
    chunks = build_chunks(words)
    E = {n: Seq(os.path.join(d3, n)) for n in ('contracts', 'house', 'split')}
    thumbs = load_chaine()
    rng = np.random.default_rng(1)
    grain = [cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 0.8)[..., None] * 0.012 for _ in range(4)]
    starts = [o(a) for _, a, _ in SCENES]
    out = sys.stdout.buffer
    for fi in (range(NFR) if only is None else only):
        t = fi / FPS
        i = max(j for j, s in enumerate(starts) if s <= t + 1e-9)
        img = render_scene(SCENES[i], t, frames, E, chunks, thumbs)
        if i > 0 and t - starts[i] < TRANS:
            k = ease_in_out((t - starts[i]) / TRANS)
            prev = render_scene(SCENES[i - 1], t, frames, E, chunks, thumbs)
            # la nouvelle scène glisse légèrement vers le haut par-dessus l'ancienne
            dy = int(70 * (1 - k))
            new = np.concatenate([img[dy:], np.repeat(img[-1:], dy, 0)]) if dy else img
            img = prev * (1 - k) + new * k
        if t > DUR - 0.25:
            img = img * clamp((DUR - t) / 0.25) + np.asarray(BG) * (1 - clamp((DUR - t) / 0.25))
        img = img + grain[fi % 4]
        out.write((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes())
        if fi % 90 == 0: print('image', fi, '/', NFR, file=sys.stderr, flush=True)

if __name__ == '__main__':
    main()
