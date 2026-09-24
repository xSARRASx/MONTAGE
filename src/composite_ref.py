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
SCENES = [      # version simple : Pierre presque tout le temps, 2 cartes seulement
    ('face_debut', 0.00, 9.10),
    ('chaine', 9.10, 11.96),
    ('face_milieu', 12.14, 25.20),
    ('masterclass', 25.20, 29.45),
    ('face_fin', 29.45, VOICE_END),
    ('fin', VOICE_END, None),
]
TRANS = 0.10   # durée des transitions entre scènes (s)

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
        t[2] = t[2].replace('courte-durée', 'courte\u00a0durée').replace('Masterclass', 'masterclass')
        if t[2].endswith('%') and len(t[2]) > 1: t[2] = t[2][:-1] + '\u00a0%'
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
        def norm(w):
            return w.lower().replace('\u00a0', '-').replace(' ', '').replace('%', '').strip('.,?!-')
        for kw in KEYWORDS:
            for j, w in enumerate(words_):
                parts_ = norm(w).split('-')          # « courte-durée » -> « courte », « durée »
                if kw.lower() in parts_ or norm(w) == kw.lower():
                    hl = j; break
            if hl >= 0: break
        out.append((start, end, words_, hl))
    return out

_subsh = {}
def subtitles_video(img, ts, chunks, y=1592):
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

PILL = (0.105, 0.125, 0.112)
def split_two(words_):
    """Coupe une phrase en deux lignes de largeurs proches."""
    best, cut = 1e9, 1
    for c in range(1, len(words_)):
        l1 = len(' '.join(words_[:c])); l2 = len(' '.join(words_[c:]))
        if max(l1, l2) < best: best, cut = max(l1, l2), c
    return [list(range(0, cut)), list(range(cut, len(words_)))]

def pill_subtitles(img, ts, chunks, rects, with_text=True):
    """Sous-titres du plan visage : une pastille sombre arrondie par phrase, de taille et de place FIXES
    (couvre toutes les positions de l'ancienne boîte pendant la phrase), texte blanc, mot-clé vert clair.
    Si l'ancienne boîte sort du cadre, la pastille devient une bande pleine largeur pour toute la phrase."""
    ci = chunk_index(ts, chunks)
    if ci is None: return
    a, b_, words_, hl = chunks[ci]
    if ts >= b_ and not rects and ci not in PILLS: return
    k = (1.0 if a < 0.05 else ease_out(clamp((ts - a) / 0.12))) if with_text else 0.0
    if ci in PILLS:
        x0, y0, x1, y1, two, band = PILLS[ci]
    elif rects:
        x0 = min(q[0] for q in rects); y0 = min(q[1] for q in rects); x1 = max(q[2] for q in rects); y1 = max(q[3] for q in rects)
        ech = (rects[0][3] - rects[0][1]) / max(1, rects[0][4]); two = (y1 - y0) / max(1e-6, ech) > 78
        band = x0 < 24 or x1 > W - 24
    else:
        if with_text and ts < b_: subtitles_video(img, ts, chunks)
        return
    one = text_img(tuple((w + ' ', (1.0, 1.0, 1.0)) for w in words_), 800, 66)
    two = one.shape[1] > 940 and len(words_) >= 2              # deux lignes seulement si la phrase est trop longue
    lines = split_two(words_) if two else [list(range(len(words_)))]
    ims = [text_img(tuple((words_[j] + (' ' if j != idx[-1] else ''), SAGE_L if j == hl else (1.0, 1.0, 1.0)) for j in idx), 800, 66)
           for idx in lines]
    tw = max(im.shape[1] for im in ims); lh = ims[0].shape[0]
    y0, y1 = y0 - 10, y1 + 10
    need = lh * len(lines) + 24
    if (y1 - y0) < need:
        c_ = (y0 + y1) / 2; y0, y1 = c_ - need / 2, c_ + need / 2
    if band:
        x0, x1, rad, cx = 0, W, 0, W / 2
    else:
        cx = (x0 + x1) / 2
        x0 = min(x0 - 10, cx - tw / 2 - 36); x1 = max(x1 + 10, cx + tw / 2 + 36)
        rad = min(28, int(y1 - y0) // 2)
    # ombre douce et floue (pas de rectangle) posée sur la zone de l'ancienne boîte, puis texte blanc
    # voile très léger et très flou sur la zone effacée (aucun bord visible)
    pad = 90
    m = np.zeros((int(y1 - y0) + 2 * pad, int(x1 - x0) + 2 * pad), np.float32)
    m[pad:-pad, pad:-pad] = 1.0
    m = cv2.GaussianBlur(m, (0, 0), 38) * 0.38
    rg = np.zeros(m.shape + (4,), np.float32); rg[..., :3] = PILL; rg[..., 3] = m
    blit(img, rg, x0 - pad, y0 - pad, 1.0)
    if with_text and k > 0:
        tot = lh * len(ims) + (len(ims) - 1) * 4
        ty = (y0 + y1) / 2 - tot / 2 - 2 + (1 - k) * 6
        for im in ims:
            sh = cv2.GaussianBlur(np.pad(im[..., 3], 20), (0, 0), 6) * 0.6
            srg = np.zeros(sh.shape + (4,), np.float32); srg[..., 3] = sh
            blit(img, srg, cx - im.shape[1] / 2 - 20, ty - 20 + 3, k)
            blit(img, im, cx - im.shape[1] / 2, ty, k); ty += lh + 4

_halo = {}
def subtitles(img, ts, chunks, dark=False, y=1540, halo=False):
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
            x_, y_ = W / 2 - im.shape[1] / 2, y + (1 - ease_out(k)) * 10
            if halo:   # lueur crème douce derrière le texte (lisible sur une photo)
                key = (tuple(parts), im.shape)
                if key not in _halo:
                    pad = 40
                    a_ = cv2.dilate(np.pad(im[..., 3], pad), np.ones((15, 15), np.uint8))
                    g = np.clip(cv2.GaussianBlur(a_, (0, 0), 16) * 1.6, 0, 0.9)
                    rg = np.zeros(g.shape + (4,), np.float32); rg[..., :3] = np.asarray(CREAM); rg[..., 3] = g
                    _halo[key] = (rg, pad)
                rg, pad = _halo[key]
                blit(img, rg, x_ - pad, y_ - pad, ease_out(k))
            blit(img, im, x_, y_, ease_out(k))

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
def subtitle_mask(f):
    """Masque serré des anciens sous-titres : on part des LETTRES (blanches / orange) posées sur la boîte
    bleu marine, puis on prend le rectangle de chaque ligne + une petite marge. Le tee-shirt bleu nuit
    (sans lettres) n'est donc plus touché."""
    y0, y1 = 590, 800
    reg = f[y0:y1].astype(np.int16); b, g, r = reg[..., 0], reg[..., 1], reg[..., 2]
    mx, mn = reg.max(2), reg.min(2)
    white = (mn > 185) & ((mx - mn) < 45)
    orange = (r > 190) & (g > 70) & (g < 180) & (b < 110) & ((r - b) > 100)
    box = (b > 45) & (b < 125) & (r < 75) & (g < 90) & (b > r + 18)
    near_box = cv2.dilate(box.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    txt = ((white | orange) & near_box).astype(np.uint8)
    mask = np.zeros(f.shape[:2], np.uint8)
    if txt.sum() > 40:
        grp = cv2.dilate(txt, np.ones((13, 31), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(grp)
        for i in range(1, n):
            x, y, w, h, area = st[i]
            if area < 250: continue
            # ligne de sous-titre : on étend jusqu'aux bords de la boîte bleu marine (≈ 10 px autour du texte)
            xa, xb = max(0, x - 8), min(f.shape[1], x + w + 8)
            ya, yb = max(0, y0 + y - 9), min(f.shape[0], y0 + y + h + 9)
            cv2.rectangle(mask, (xa, ya), (xb, yb), 255, -1)
        # on ajoute les pixels de boîte collés à ces rectangles (coins arrondis de la boîte)
        boxfull = np.zeros_like(mask); boxfull[y0:y1] = box.astype(np.uint8) * 255
        grow = cv2.dilate(mask, np.ones((13, 17), np.uint8))
        mask = np.maximum(mask, cv2.bitwise_and(boxfull, grow))
    # barre de progression (fine ligne en bas) : lignes où l'on trouve une longue trace orange ou gris clair
    bar = f[772:804].astype(np.int16); bb, bg, br = bar[..., 0], bar[..., 1], bar[..., 2]
    bar_px = ((br > 180) & (bg > 60) & (bg < 180) & (bb < 110)) | ((bar.min(2) > 120) & ((bar.max(2) - bar.min(2)) < 30))
    rows = np.nonzero(bar_px.mean(1) > 0.25)[0]
    if len(rows):
        mask[772 + rows.min() - 2:772 + rows.max() + 3, 8:472] = 255
    mask[782:794, 18:462] = 255          # la fine barre grise est toujours à cet endroit
    return mask

def old_box_rects(mask):
    """Rectangles (x0, y0, x1, y1) de chaque ligne de l'ancien sous-titre, triés de haut en bas."""
    m = mask.copy(); m[766:] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats((m > 0).astype(np.uint8))
    rects = [(x, y, x + w, y + h) for (x, y, w, h, area) in st[1:] if area > 300 and h > 12]
    return sorted(rects, key=lambda r: r[1])

def clean_frame(frames, si):
    """Efface les anciens sous-titres et la barre de progression (inpainting sur un masque serré)."""
    if si in _inp: return _inp[si]
    f = frames[si]
    mask = subtitle_mask(f)
    out = cv2.inpaint(f, mask, 5, cv2.INPAINT_TELEA)
    # lissage léger À L'INTÉRIEUR du masque (supprime les stries sans créer de tache)
    m = cv2.erode(mask, np.ones((3, 3), np.uint8)).astype(np.float32) / 255
    soft = cv2.GaussianBlur(m, (0, 0), 2.0)[..., None]
    smooth_ = cv2.GaussianBlur(out, (0, 0), 3.5)
    out = (out * (1 - soft) + smooth_ * soft).astype(np.uint8)
    if len(_inp) > 90: _inp.clear()
    _inp[si] = (out, mask)
    return _inp[si]

S0 = H / 848
BOTTOM_SHADE = np.clip((np.arange(H, dtype=np.float32) - 1250) / 670, 0, 1)[:, None, None] ** 1.3 * 0.42

# moments où le rush montre encore en haut le titre ou les anciens bandeaux orange/bleu
FENETRES_HAUT = [(0.0, 3.0), (4.55, 8.2), (12.35, 16.35), (19.25, 23.25), (25.25, 29.4)]

def poids_serre(ts):
    """0 = cadrage normal, 1 = cadrage légèrement resserré (haut du rush hors champ), transitions douces."""
    w = 0.0
    for a, b in FENETRES_HAUT:
        w = max(w, ease_in_out((ts - (a - 0.5)) / 0.5) * (1 - ease_in_out((ts - b) / 0.5)))
    return w

def face_geom(ts, zoom=None):
    """Cadrage du plan visage : sortie p -> source q = A + (p - P) / s.
    Normal (comme la v4) : zoom 1,18 ancré sous le visage. Resserré : zoom 1,38 calé sur le bas du rush,
    juste assez pour sortir les anciens bandeaux du haut."""
    w = poids_serre(ts)
    start, idx = shot_start(ts)
    push = 0.02 * ease_in_out((ts - start) / 4)
    s_n = S0 * (1.18 + push); A_n = np.array([226.0, 636.0]); P_n = np.array([W / 2, H * 0.75])
    s_t = S0 * (1.38 + push); A_t = np.array([226.0, 846.0]); P_t = np.array([W / 2, float(H)])
    # interpolation de la correspondance sortie -> source (matrices affines)
    def mat(s_, A_, P_): return np.array([[1 / s_, 0, A_[0] - P_[0] / s_], [0, 1 / s_, A_[1] - P_[1] / s_]], np.float64)
    M = mat(s_n, A_n, P_n) * (1 - w) + mat(s_t, A_t, P_t) * w
    s = 1 / M[0, 0]
    P = np.array([W / 2, H / 2]); A = M[:, :2] @ P + M[:, 2]
    return s, A, P, M

def box_rects_out(mask, s, A, P):
    out = []
    for (x0, y0, x1, y1) in old_box_rects(mask):
        p0 = (np.array([x0, y0], float) - A) * s + P; p1 = (np.array([x1, y1], float) - A) * s + P
        out.append((p0[0], p0[1], p1[0], p1[1], y1 - y0))
    return out

FACE_ZOOM = {}
ZOOM_SIMPLE = 1.60
PILLS = {}          # index de phrase -> pastille stable (x0, y0, x1, y1, deux_lignes, bande_pleine_largeur)

def chunk_index(ts, chunks):
    cur = None
    for i, c in enumerate(chunks):
        if c[0] - 0.02 <= ts: cur = i
    return cur

def precompute_pills(frames, chunks):
    """Une pastille stable par phrase : union de toutes les positions de l'ancienne boîte pendant la phrase
    (sur les plans visage). Plus de pastille qui clignote ou qui change de forme au milieu d'une phrase."""
    acc = {}
    starts_ = [o(a) for _, a, _ in SCENES]
    for fi in range(NFR):
        t = fi / FPS
        if t >= T_END: break
        i = max(j for j, s_ in enumerate(starts_) if s_ <= t + 1e-9)
        kind, a, b = SCENES[i]
        if not kind.startswith('face_'): continue
        ts = out_to_src(t)
        si = min(len(frames) - 1, int(round(ts * 30)))
        s, A, P, M = face_geom(ts, FACE_ZOOM.get(kind, ZOOM_SIMPLE))
        rects = box_rects_out(subtitle_mask(frames[si]), s, A, P)
        ci = chunk_index(ts, chunks)
        if ci is None or not rects: continue
        x0 = min(r[0] for r in rects); y0 = min(r[1] for r in rects); x1 = max(r[2] for r in rects); y1 = max(r[3] for r in rects)
        ech = (rects[0][3] - rects[0][1]) / max(1, rects[0][4])
        two = (y1 - y0) / max(1e-6, ech) > 78
        if ci in acc:
            q = acc[ci]; acc[ci] = [min(q[0], x0), min(q[1], y0), max(q[2], x1), max(q[3], y1), q[4] or two]
        else:
            acc[ci] = [x0, y0, x1, y1, two]
    for ci, q in acc.items():
        band = q[0] < 24 or q[2] > W - 24
        PILLS[ci] = (q[0], q[1], q[2], q[3], q[4], band)

def draw_face(img, frames, t, ts, zoom=1.18, chunks=None, face_text=True):
    si = min(len(frames) - 1, int(round(ts * 30)))
    f, emask = clean_frame(frames, si)
    s, A, P, M = face_geom(ts, zoom)
    im = cv2.warpAffine(f, M, (W, H), flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)
    im = im[..., ::-1].astype(np.float32) / 255
    bl = cv2.GaussianBlur(im, (0, 0), 1.6)
    im = np.clip(im + (im - bl) * 0.6, 0, 1)
    lum = im @ np.array([0.299, 0.587, 0.114], np.float32)
    im = lum[..., None] + (im - lum[..., None]) * 0.93
    im = np.clip((im - 0.5) * 1.07 + 0.5 + np.array([0.012, 0.004, -0.010], np.float32), 0, 1)
    img[:] = im * (1 - BOTTOM_SHADE)
    # l'ancienne boîte de sous-titre est recouverte par la nouvelle pastille (même place, même taille) :
    # là où elle cachait déjà le bas de la bouche dans le rush, rien n'est inventé ni flouté.
    rects = box_rects_out(emask, s, A, P)
    if chunks is not None:
        pill_subtitles(img, ts, chunks, rects, face_text)

# ------------------------------------------------------------------ photos réelles (Unsplash) et écran du père
YY_, XX_ = np.mgrid[0:H, 0:W].astype(np.float32)
_photos = {}
def photo(name):
    if name not in _photos:
        p = os.path.join(ROOT, 'assets', 'photos', name)
        _photos[name] = cv2.imread(p)[..., ::-1].astype(np.float32) / 255
    return _photos[name]

def photo_bg(img, name, t, t0, dur, cx, cy, z0=1.0, z1=1.08, veil=0.55, veil_h=640):
    """Photo plein écran recadrée en 9:16 autour de (cx, cy) (coordonnées relatives), mouvement lent.
    Renvoie la matrice 2x3 photo -> écran (pour placer des éléments sur la photo)."""
    ph = photo(name); h, w = ph.shape[:2]
    k = ease_in_out((t - t0) / dur)
    s = max(W / w, H / h) * (z0 + (z1 - z0) * k)
    ox = clamp(cx * w * s - W / 2, 0, w * s - W); oy = clamp(cy * h * s - H / 2, 0, h * s - H)
    M = np.array([[s, 0, -ox], [0, s, -oy]], np.float64)
    img[:] = cv2.warpAffine(ph, M, (W, H), flags=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    if veil:
        # voile plein sur la zone du titre (55 % de veil_h), puis fondu jusqu'à veil_h
        g = np.clip((veil_h - np.arange(H, dtype=np.float32)) / (veil_h * 0.45), 0, 1)[:, None, None] ** 1.2 * veil
        img[:] = img * (1 - g) + np.asarray(BG, np.float32) * g
    return M

_pere = {}
def pere_img(vid, x0):
    """Recadrage du père dans une de ses miniatures (zone sans texte)."""
    k = (vid, x0)
    if k not in _pere:
        im = cv2.imread(os.path.join(ROOT, 'assets', 'youtube', 'thumbs', vid + '.jpg'))[..., ::-1].astype(np.float32) / 255
        _pere[k] = im[:, x0:]
    return _pere[k]

_clips = {}
def clip_frame(name, tc):
    """Image d'un extrait vidéo réel de Sébastien MORE (assets/videos, sans son), à l'instant tc (s)."""
    if name not in _clips:
        cap = cv2.VideoCapture(os.path.join(ROOT, 'assets', 'videos', name)); fr = []
        while True:
            ok, f = cap.read()
            if not ok: break
            fr.append(f[..., ::-1].astype(np.float32) / 255)
        _clips[name] = fr
    fr = _clips[name]
    return fr[int(clamp(tc * 30, 0, len(fr) - 1))]

def ecran_masterclass(t, t0, vid='sWiie3c__Lo', x0=660, sw=1060, sh=650, texte=('La conciergerie', 'Airbnb'), clip=None):
    """Image affichée sur l'écran de l'ordinateur : le lecteur de la masterclass avec Sébastien MORE
    (extrait vidéo réel si « clip » est fourni, sinon image tirée d'une miniature)."""
    sl = np.empty((sh, sw, 3), np.float32); sl[:] = np.asarray(CREAM, np.float32)
    if clip:
        dad = clip_frame(clip, max(0.0, t - t0))
        dh = sh; dw = min(620, int(dad.shape[1] * dh / dad.shape[0]))
        z = 1.0
    else:
        dad = pere_img(vid, x0)
        dh = sh; dw = int(dad.shape[1] * dh / dad.shape[0])
        z = 1.0 + 0.06 * clamp((t - t0) / 4.5)                  # léger zoom : l'image vit
    sc_ = max(dw / dad.shape[1], dh / dad.shape[0]) * z
    big = cv2.resize(dad, (max(dw, int(dad.shape[1] * sc_)), max(dh, int(dad.shape[0] * sc_))), interpolation=cv2.INTER_AREA)
    cy0 = (big.shape[0] - dh) // 3; cx0 = (big.shape[1] - dw) // 2
    sl[:, sw - dw:] = big[cy0:cy0 + dh, cx0:cx0 + dw]
    # fondu entre le panneau texte et l'image du père
    fade = np.clip((np.arange(sw, dtype=np.float32) - (sw - dw)) / 90, 0, 1)[None, :, None]
    sl[:, sw - dw:] = sl[:, sw - dw:] * fade[:, sw - dw:] + np.asarray(CREAM, np.float32) * (1 - fade[:, sw - dw:])
    tmp = (sl * 255).astype(np.uint8)
    def txt(parts, wgt, size, x, y, track=0):
        im = text_img(tuple(parts), wgt, size, track)
        a_ = im[..., 3:4]; h_, w_ = im.shape[:2]
        reg = sl[y:y + h_, x:x + w_]; reg[:] = reg * (1 - a_[:reg.shape[0], :reg.shape[1]]) + im[:reg.shape[0], :reg.shape[1], :3] * a_[:reg.shape[0], :reg.shape[1]]
    ts_ = 58 if not clip else 48
    txt([('MASTERCLASS GRATUITE', SAGE)], 800, 22, 46, 70, 2)
    txt([(texte[0], INK)], 800, ts_, 42, 118)
    txt([(texte[1], SAGE)], 800, ts_, 42, 118 + int(ts_ * 1.15))
    txt([('avec Sébastien MORE', MUTED)], 700, 28, 46, 130 + int(ts_ * 2.4))
    # barre de lecture
    y = sh - 34
    sl[y:y + 8, 40:sw - 40] = np.asarray(LINE, np.float32)
    pr = int((sw - 80) * (0.18 + 0.1 * clamp((t - t0) / 5)))
    sl[y:y + 8, 40:40 + pr] = np.asarray(SAGE, np.float32)
    cv2.circle(sl, (40 + pr, y + 4), 11, tuple(float(v) for v in SAGE), -1, cv2.LINE_AA)
    return sl

def incruste_ecran(img, M, quad, ecran, op=1.0):
    """Place « ecran » dans le quadrilatère « quad » (coordonnées photo) de la photo transformée par M."""
    q = np.array(quad, np.float32)
    q = (np.hstack([q, np.ones((4, 1), np.float32)]) @ M.T).astype(np.float32)
    sh, sw = ecran.shape[:2]
    P = cv2.getPerspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]), q)
    warped = cv2.warpPerspective(ecran, P, (W, H), flags=cv2.INTER_AREA)
    m = np.zeros((H * 2, W * 2), np.uint8); cv2.fillConvexPoly(m, (q * 2).astype(np.int32), 255, cv2.LINE_AA)
    m = cv2.resize(m, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32)[..., None] / 255 * op
    # léger reflet sur la dalle
    g = np.clip((XX_ + YY_ * 0.5 - (q[:, 0].min() + q[:, 1].min() * 0.5)) / 900, 0, 1)
    warped = warped + (0.06 * (1 - g))[..., None]
    img[:] = img * (1 - m) + np.clip(warped, 0, 1) * m

def info_pill(img, parts, x, y, op, size=34):
    im = text_img(tuple(parts), 700, size)
    pw, ph = im.shape[1] + 56, im.shape[0] + 26
    soft_shadow(img, x, y, pw, ph, ph // 2, 0.18 * op, 16, 10)
    fill_rrect(img, x, y, pw, ph, ph // 2, (1.0, 1.0, 1.0), op)
    blit(img, im, x + 28, y + 11, op)

# ------------------------------------------------------------------ logos plateformes
_logos = {}
def logo_pill(name, h_logo):
    """Logo officiel (Airbnb / Booking.com) dans une pastille blanche arrondie."""
    k = (name, h_logo)
    if k not in _logos:
        im = cv2.imread(os.path.join(ROOT, 'assets', 'logos', name + '.png'), cv2.IMREAD_UNCHANGED).astype(np.float32) / 255
        im[..., :3] = im[..., 2::-1][..., :3]
        w = int(im.shape[1] * h_logo / im.shape[0])
        im = cv2.resize(im, (w, h_logo), interpolation=cv2.INTER_AREA)
        padx, pady = int(h_logo * 0.55), int(h_logo * 0.42)
        W_, H_ = w + 2 * padx, h_logo + 2 * pady
        card = np.zeros((H_, W_, 4), np.float32); card[..., :3] = 1.0; card[..., 3] = rrect_mask(W_, H_, H_ // 2)
        a_ = im[..., 3:4]
        card[pady:pady + h_logo, padx:padx + w, :3] = card[pady:pady + h_logo, padx:padx + w, :3] * (1 - a_) + im[..., :3] * a_
        _logos[k] = card
    return _logos[k]

def pop_logo(img, t, t0, name, h_logo, x, y, anchor='left', until=None):
    if t < t0: return
    if until is not None and t > until + 0.3: return
    k = ease_out_back((t - t0) / 0.45, 1.8)
    card = logo_pill(name, h_logo)
    sc = max(0.05, 0.6 + 0.4 * k)
    im = cv2.resize(card, (max(2, int(card.shape[1] * sc)), max(2, int(card.shape[0] * sc))), interpolation=cv2.INTER_AREA)
    if anchor == 'center': x = x - im.shape[1] / 2
    op = clamp((t - t0) / 0.2) * (1 - clamp((t - until) / 0.3) if until is not None else 1)
    soft_shadow(img, x, y + (card.shape[0] - im.shape[0]) / 2, im.shape[1], im.shape[0], im.shape[0] // 2, 0.22 * op, 18, 12)
    blit(img, im, x, y + (card.shape[0] - im.shape[0]) / 2, op)

def pop_name(img, t, t0, until=None):
    """Prénom en surimpression (« Pierre ») quand il se présente."""
    if t < t0: return
    op, dy = appear(t, t0, 0.35)
    if until is not None: op *= 1 - clamp((t - until) / 0.3)
    if op <= 0: return
    im = text_img((('Pierre', INK),), 800, 58)
    sub_ = text_img((('Conciergerie Airbnb', MUTED),), 700, 30)
    pw = max(im.shape[1], sub_.shape[1]) + 76; ph = 150
    x, y = 70, 250 + dy
    soft_shadow(img, x, y, pw, ph, 30, 0.22 * op, 18, 12)
    fill_rrect(img, x, y, pw, ph, 30, CREAM, op)
    img[int(y) + 22:int(y) + ph - 22, x + 26:x + 32] = img[int(y) + 22:int(y) + ph - 22, x + 26:x + 32] * (1 - op) + np.asarray(SAGE) * op
    blit(img, im, x + 50, y + 12, op)
    blit(img, sub_, x + 52, y + 88, op)

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
    t0 = o(5.65)
    label(img, t, t0, "L'ÉQUIPE")
    title(img, t, t0 + 0.05, [[('Pierre', INK)], [('& son père.', MUTED)]])
    rows = [(o(6.05), '4 ans', 'à travailler ensemble'), (o(7.2), '10 ans', "d'accompagnement en conciergerie")]
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
    t0 = o(9.10)
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
            title(img, t, o(9.1), [[('10 ans', SAGE), (" d'expérience", INK)]], y=345)
            op2, dy2 = appear(t, o(9.25))
            put_text(img, [("dans l'accompagnement en conciergerie", MUTED)], 700, 38, 80, 455 + dy2, op2)
    else:
        k = ease_out((t - swap) / (o(10.8) - swap))
        n = int(round(1500 * k / 10) * 10)
        title(img, t, swap, [[('+' + '{:,}'.format(n).replace(',', ' '), SAGE), (' vidéos.', INK)]], y=345)
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
    photo_bg(img, 'cles.jpg', t, t0, o(16.45) - t0 + TRANS, 0.45, 0.50, 1.0, 1.07, veil=0.66, veil_h=700)
    label(img, t, t0, 'LA CONCIERGERIE')
    swap = o(14.35)
    if t < swap:
        title(img, t, t0 + 0.05, [[("C'est quoi ?", INK)]])
        pop_logo(img, t, o(12.95), 'airbnb', 78, 80, 330)
    else:
        title(img, t, swap, [[('Accompagner', INK)], [('des propriétaires.', SAGE)]])

def card_commission(img, t, E):
    t0 = o(19.10)
    photo_bg(img, 'revenus.jpg', t, t0, o(23.40) - t0 + TRANS, 0.40, 0.55, 1.0, 1.08, veil=0.8, veil_h=820)
    label(img, t, t0, 'LE MODÈLE ÉCONOMIQUE')
    title(img, t, t0 + 0.05, [[('En échange.', INK)]])
    k1 = ease_out((t - o(20.55)) / 0.5); k2 = ease_out((t - o(20.95)) / 0.5)
    if t >= o(20.55):
        a_ = int(round(20 * k1)); b_ = int(round(25 * k2)) if t >= o(20.95) else None
        parts = [('%d' % a_, SAGE)] + ([('\u00a0à\u00a0%d\u00a0%%' % b_, SAGE)] if b_ is not None else [('\u00a0%', SAGE)])
        op, dy = appear(t, o(20.55))
        put_text(img, parts, 800, 132, 74, 300 + dy, op)
    op, dy = appear(t, o(21.9))
    if op > 0: info_pill(img, [('de commission sur le revenu locatif', INK)], 76, 470 + dy, op)

MC_IMG = None
ECRAN_QUAD = None
def ordinateur_quad():
    global ECRAN_QUAD
    if ECRAN_QUAD is None:
        cr = json.load(open(os.path.join(ROOT, 'assets', 'photos', 'credits.json'), encoding='utf-8'))
        ECRAN_QUAD = [c for c in cr if c['fichier'] == 'ordinateur.jpg'][0]['coins_ecran']
    return ECRAN_QUAD

def card_masterclass(img, t, E):
    t0 = o(25.20)
    M = photo_bg(img, 'ordinateur.jpg', t, t0, o(29.45) - t0 + TRANS, 0.44, 0.47, 1.55, 1.62, veil=0.9, veil_h=840)
    incruste_ecran(img, M, ordinateur_quad(), ecran_masterclass(t, t0, clip='pere_masterclass.mp4'))
    label(img, t, t0, 'MASTERCLASS GRATUITE')
    title(img, t, t0 + 0.05, [[('Une masterclass', INK)]])
    op, dy = appear(t, o(28.1))
    put_text(img, [('100\u00a0% gratuite.', SAGE)], 800, 86, 76, 301 + dy, op)

def card_fin(img, t, E):
    t0 = T_END
    M = photo_bg(img, 'ordinateur.jpg', t, t0, END_HOLD + 0.5, 0.44, 0.50, 1.35, 1.45, veil=0.9, veil_h=640)
    incruste_ecran(img, M, ordinateur_quad(), ecran_masterclass(t, t0, clip='pere_fin.mp4'))
    op, dy = appear(t, t0 + TRANS)
    im = text_img((('MASTERCLASS GRATUITE', CREAM),), 700, 24, 3)
    fill_rrect(img, 76, 140 + dy, im.shape[1] + 44, 52, 26, INK, op)
    blit(img, im, 98, 150 + dy, op)
    title(img, t, t0 + 0.12, [[('Ta conciergerie.', INK)], [('Lance-toi.', SAGE)]], y=230)
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
    if op4 > 0: info_pill(img, [('100\u00a0% gratuite · clique autour de la vidéo', INK)], 76, 1400 + dy4, op4, 30)

# ------------------------------------------------------------------ rendu d'une scène
def render_scene(sc, t, frames, E, chunks, thumbs, ts_max=None, face_text=True):
    """Rend une scène SANS sous-titres (ils sont posés une seule fois après les transitions).
    ts_max : fige la vidéo source (plan sortant d'une transition, pour ne jamais montrer la suite du rush)."""
    kind, a, b = sc
    ts = out_to_src(min(t, T_END - 1e-3))
    if ts_max is not None: ts = min(ts, ts_max)
    dark = False
    img = (BG_DARK if dark else BG_LIGHT).copy()
    t0 = o(a)
    if kind == 'face_hook':
        draw_face(img, frames, t, ts, zoom=FACE_ZOOM['face_hook'], chunks=chunks if t < T_END else None, face_text=face_text)
    elif kind == 'face_pierre':         # zoom serré : le haut du rush (ancien bandeau) reste hors cadre
        draw_face(img, frames, t, ts, zoom=FACE_ZOOM['face_pierre'], chunks=chunks if t < T_END else None, face_text=face_text)
        pop_name(img, t, o(4.84))
    elif kind.startswith('face_'):
        draw_face(img, frames, t, ts, zoom=ZOOM_SIMPLE, chunks=chunks if t < T_END else None, face_text=face_text)
        if kind == 'face_debut':
            pop_name(img, t, o(4.84), until=o(7.0))
        if kind == 'face_milieu':
            pop_logo(img, t, o(12.95), 'airbnb', 90, W / 2, 200, 'center', until=o(15.5))
            pop_logo(img, t, o(16.62), 'airbnb', 90, W / 2 - 250, 200, 'center', until=o(19.2))
            pop_logo(img, t, o(16.95), 'booking', 70, W / 2 + 230, 210, 'center', until=o(19.2))
        if kind == 'face_lcd':          # « location courte durée » : les plateformes
            pop_logo(img, t, o(16.62), 'airbnb', 104, W / 2, 190, 'center')
            pop_logo(img, t, o(16.95), 'booking', 80, W / 2, 420, 'center')
    elif kind == 'chambre': card_chambre(img, t, E)
    elif kind == 'contrats': card_contrats(img, t, E)
    elif kind == 'equipe': card_equipe(img, t, E)
    elif kind == 'chaine': card_chaine(img, t, E, thumbs)
    elif kind == 'conciergerie': card_conciergerie(img, t, E)
    elif kind == 'commission': card_commission(img, t, E)
    elif kind == 'masterclass': card_masterclass(img, t, E)
    elif kind == 'fin': card_fin(img, t, E)
    if kind not in ('fin', 'chambre', 'conciergerie', 'commission', 'masterclass') and not kind.startswith('face_'):
        put_text(img, [('locationcourteduree.fr', (0.55, 0.58, 0.55) if dark else MUTED)], 600, 26, W / 2, 1810, 0.9, 'center', 1)
    return img

def draw_subs(img, sc, t, chunks):
    """Sous-titres de la scène active : blancs sur la vidéo, foncés (ou crème) sur les cartes."""
    kind = sc[0]
    if kind == 'fin' or t >= T_END: return
    ts = out_to_src(min(t, T_END - 1e-3))
    if kind.startswith('face_'): subtitles_video(img, ts, chunks)
    else: subtitles(img, ts, chunks, False, halo=kind in ('conciergerie', 'commission', 'masterclass'))

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
    precompute_pills(frames, chunks)
    E = {n: Seq(os.path.join(d3, n)) for n in ('contracts', 'house', 'split')}
    thumbs = load_chaine()
    rng = np.random.default_rng(1)
    grain = [cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 0.8)[..., None] * 0.012 for _ in range(4)]
    starts = [o(a) for _, a, _ in SCENES]
    out = sys.stdout.buffer
    for fi in (range(NFR) if only is None else only):
        t = fi / FPS
        i = max(j for j, s in enumerate(starts) if s <= t + 1e-9)
        trans = i > 0 and t - starts[i] < TRANS
        kk = ease_in_out((t - starts[i]) / TRANS) if trans else 1.0
        img = render_scene(SCENES[i], t, frames, E, chunks, thumbs, face_text=kk >= 0.5)
        if trans:
            k = kk
            pk, pa, pb = SCENES[i - 1]
            prev = render_scene(SCENES[i - 1], t, frames, E, chunks, thumbs,
                                ts_max=(pb - 1 / 30) if pk.startswith('face_') else None, face_text=kk < 0.5)
            # la nouvelle scène glisse légèrement vers le haut par-dessus l'ancienne
            dy = int(70 * (1 - k))
            new = np.concatenate([img[dy:], np.repeat(img[-1:], dy, 0)]) if dy else img
            img = prev * (1 - k) + new * k
        dominante = SCENES[i]
        if trans and (t - starts[i]) / TRANS < 0.5:
            dominante = SCENES[i - 1]
        if not dominante[0].startswith('face_'):      # les plans visage portent déjà leurs sous-titres
            draw_subs(img, dominante, t, chunks)
        if t > DUR - 0.25:
            img = img * clamp((DUR - t) / 0.25) + np.asarray(BG) * (1 - clamp((DUR - t) / 0.25))
        img = img + grain[fi % 4]
        out.write((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes())
        if fi % 90 == 0: print('image', fi, '/', NFR, file=sys.stderr, flush=True)

if __name__ == '__main__':
    main()
