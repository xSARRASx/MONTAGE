"""Compositing final : cuts, upscale 1080x1920, caméra dynamique, étalonnage, 3D, effets 2D, grain.

Usage : python3 composite.py <src.mp4> <dossier_3d> <sortie_frames.y4m|pipe>
Écrit des images BGR brutes sur stdout (à piper dans ffmpeg).
"""
import sys, os, glob, math
import numpy as np, cv2

W, H, FPS = 1080, 1920, 30
SRC_W, SRC_H = 480, 848

# ------------------------------------------------------------------ montage (temps source)
# On resserre les silences entre les phrases (les coupes tombent sur les jump-cuts existants).
KEEP = [(0.0, 11.96), (12.14, 18.50), (18.77, 23.78), (24.02, 37.2333)]
SHOT_CUTS = [4.37, 11.93, 18.47, 23.73, 35.03]          # changements de plan (source)
END_CARD = 35.03

def out_to_src(t):
    acc = 0.0
    for a, b in KEEP:
        if t < acc + (b - a): return a + (t - acc)
        acc += b - a
    return KEEP[-1][1] - 1e-3

def src_to_out(ts):
    acc = 0.0
    for a, b in KEEP:
        if ts < b: return acc + max(0.0, ts - a)
        acc += b - a
    return acc

DUR_OUT = sum(b - a for a, b in KEEP)
NFR = int(DUR_OUT * FPS)

# ------------------------------------------------------------------ utilitaires
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease_out(x): x = clamp(x); return 1 - (1 - x) ** 3
def ease_in(x): x = clamp(x); return x ** 3
def ease_in_out(x): x = clamp(x); return x * x * (3 - 2 * x)
def bump(t, t0, rise=0.08, decay=0.9):
    """Impulsion rapide puis retour doux (pour les punch-in)."""
    if t < t0: return 0.0
    if t < t0 + rise: return ease_out((t - t0) / rise)
    return math.exp(-(t - t0 - rise) / decay * 2.2)

def alpha_over(dst, rgba, x, y, opacity=1.0):
    """Colle une image BGRA (float 0..1 premult non) sur dst (float BGR) en (x, y) coin haut-gauche."""
    h, w = rgba.shape[:2]
    x0, y0 = max(0, x), max(0, y); x1, y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0: return
    sub = rgba[y0 - y:y1 - y, x0 - x:x1 - x]
    a = sub[..., 3:4] * opacity
    dst[y0:y1, x0:x1] = dst[y0:y1, x0:x1] * (1 - a) + sub[..., :3] * a

def add_layer(dst, col, alpha, mode='normal'):
    a = alpha[..., None]
    if mode == 'screen':
        dst[:] = 1 - (1 - dst) * (1 - np.asarray(col) * a)
    elif mode == 'add':
        dst[:] = dst + np.asarray(col) * a
    else:
        dst[:] = dst * (1 - a) + np.asarray(col) * a

WHITE = (1.0, 1.0, 1.0)
CHAMPAGNE = (0.72, 0.88, 1.0)        # BGR, reflet doré discret
WARM_WHITE = (0.93, 0.97, 1.0)

# ------------------------------------------------------------------ étalonnage
def build_grade():
    x = np.linspace(0, 1, 256)
    s = x * x * (3 - 2 * x)
    base = 0.78 * x + 0.22 * s                      # contraste doux en S
    lift = 0.012
    v = np.clip(base * (1 - lift) + lift, 0, 1)     # étalonnage neutre : pas de virage orange/bleu
    return np.stack([v, v, v], 1).astype(np.float32)
GRADE = build_grade()

yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
_r = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H * 0.48) / (H * 0.62)) ** 2)
VIGNETTE = (1 - 0.30 * np.clip(_r - 0.45, 0, 1) ** 1.6)[..., None].astype(np.float32)

rng = np.random.default_rng(3)
GRAIN = [cv2.GaussianBlur(rng.normal(0, 1, (H, W)).astype(np.float32), (0, 0), 0.7)[..., None] * 0.022 for _ in range(6)]

def grade(img):
    idx = np.clip(img * 255, 0, 255).astype(np.uint8)
    out = np.empty_like(img)
    for c in range(3): out[..., c] = GRADE[idx[..., c], c]
    lum = out @ np.array([0.114, 0.587, 0.299], np.float32)
    out = lum[..., None] + (out - lum[..., None]) * 1.04
    return np.clip(out, 0, 1)

# ------------------------------------------------------------------ caméra
S0 = H / SRC_H                     # 2.264 : la hauteur remplit l'écran
OX = (SRC_W * S0 - W) / 2          # recadrage horizontal centré

PUNCH = [  # (temps source, amplitude)
    (0.96, 0.045), (2.66, 0.02), (6.10, 0.02), (9.14, 0.03), (10.44, 0.04), (13.64, 0.03),
    (16.58, 0.02), (20.58, 0.03), (20.94, 0.03), (24.98, 0.035), (27.56, 0.03), (28.34, 0.02),
    (30.60, 0.02), (32.74, 0.04), (34.64, 0.05)]
SHAKE = [(0.96, 7), (34.64, 10), (35.03, 14)]

def shot_index(ts):
    return sum(1 for c in SHOT_CUTS if ts >= c)

def camera(t_out, ts):
    """Retourne la matrice 2x3 sortie -> source."""
    if ts >= END_CARD:
        k = ts - END_CARD
        z = 1.0 + 0.02 * ease_in_out(k / 2.2) + 0.03 * bump(ts, END_CARD, 0.05, 0.25)
        ax, ay = W * 0.5, H * 0.5
    else:
        i = shot_index(ts)
        start = ([0.0] + SHOT_CUTS)[i]
        z = 1.0 + (0.025 if i % 2 else 0.0) + 0.025 * ease_in_out((ts - start) / 4.0)
        z += sum(a * bump(ts, t0) for t0, a in PUNCH)
        z = min(z, 1.07)
        ax, ay = W * 0.47, H * 0.45
    dx = dy = rot = 0.0
    for t0, amp in SHAKE:
        if t0 <= ts < t0 + 0.5:
            e = math.exp(-(ts - t0) * 9) * amp
            dx += e * math.sin(ts * 91); dy += e * math.cos(ts * 77); rot += e * 0.0009 * math.sin(ts * 63)
    c, s = math.cos(rot), math.sin(rot)
    # sortie p -> q = R^-1 (p - A - d)/z + A  -> source = (q + (OX, 0)) / S0
    A = np.array([[c, s], [-s, c]]) / z
    b = -A @ np.array([ax + dx, ay + dy]) + np.array([ax, ay])
    M = np.zeros((2, 3)); M[:, :2] = A / S0; M[:, 2] = (b + np.array([OX, 0])) / S0
    return M

def zoom_blur(img, strength):
    if strength <= 0.01: return img
    acc = img.copy(); n = 5
    for k in range(1, n + 1):
        sc = 1 + 0.035 * strength * k
        M = cv2.getRotationMatrix2D((W / 2, H * 0.45), 0, sc)
        acc += cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT)
    return acc / (n + 1)

# ------------------------------------------------------------------ éléments 3D
class Element:
    def __init__(self, folder, name, t_src, box, extra=None):
        fs = sorted(glob.glob(os.path.join(folder, name, name + '_*.png')))
        self.name, self.n = name, len(fs)
        self.t0 = src_to_out(t_src)
        self.frames = [cv2.imread(f, cv2.IMREAD_UNCHANGED) for f in fs]
        self.cache = {}
        if not fs:
            self.scale, self.ox, self.oy = 1, 0, 0; return
        # cadrage sur l'image la plus « pleine » (l'objet posé), pas sur toute la trajectoire
        areas = [int((f[..., 3] > 8).sum()) for f in self.frames]
        al = self.frames[int(np.argmax(areas))][..., 3]
        ys, xs = np.nonzero(al > 8)
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        cx, cy, bw, bh = box
        self.scale = min(bw * W / (x1 - x0), bh * H / (y1 - y0))
        self.ox = cx * W - (x0 + x1) / 2 * self.scale
        self.oy = cy * H - (y0 + y1) / 2 * self.scale
        self.cache = {}

    def frame(self, t_out):
        i = int(round((t_out - self.t0) * FPS))
        return i if 0 <= i < self.n else None

    def get(self, i):
        if i not in self.cache:
            f = self.frames[i].astype(np.float32) / 255
            f = cv2.resize(f, None, fx=self.scale, fy=self.scale, interpolation=cv2.INTER_AREA if self.scale < 1 else cv2.INTER_CUBIC)
            # ombre portée douce
            a = f[..., 3]
            pad = 40
            sh = np.zeros((a.shape[0] + 2 * pad, a.shape[1] + 2 * pad), np.float32)
            sh[pad + 16:pad + 16 + a.shape[0], pad:pad + a.shape[1]] = a
            sh = cv2.GaussianBlur(sh, (0, 0), 12) * 0.38
            self.cache[i] = (f, sh, pad)
        return self.cache[i]

    def draw(self, img, t_out, dx=0.0, dy=0.0, opacity=1.0):
        i = self.frame(t_out)
        if i is None: return None
        f, sh, pad = self.get(i)
        x, y = int(round(self.ox + dx)), int(round(self.oy + dy))
        shadow = np.zeros(sh.shape + (4,), np.float32); shadow[..., 3] = sh
        alpha_over(img, shadow, x - pad, y - pad, opacity)
        alpha_over(img, f, x, y, opacity)
        return i

    def to_screen(self, px, py):
        return self.ox + px * self.scale, self.oy + py * self.scale

    def tip(self, i):
        """Pointe (coin haut-gauche du contenu) d'une image rendue — utile pour le curseur."""
        a = self.frames[i][..., 3]
        ys, xs = np.nonzero(a > 60)
        j = np.argmin(xs + ys)
        return self.to_screen(xs[j], ys[j])

# ------------------------------------------------------------------ effets 2D
def ring(img, t, t0, cx, cy, col=WHITE, dur=0.55, r_max=150, width=10):
    k = (t - t0) / dur
    if not 0 <= k <= 1: return
    for j, delay in enumerate((0.0, 0.18)):
        kk = clamp((k - delay) / (1 - delay))
        if kk <= 0: continue
        r = int(r_max * ease_out(kk)); a = (1 - kk) ** 1.5
        m = np.zeros((H, W), np.float32)
        cv2.circle(m, (int(cx), int(cy)), max(r, 1), 1.0, max(1, int(width * (1 - kk) + 2)), cv2.LINE_AA)
        add_layer(img, col, m * a * 0.9)

SPARK_RNG = np.random.default_rng(11)
def sparkles(img, t, t0, cx, cy, n=14, spread=260, dur=0.8, seed=0, col=CHAMPAGNE):
    k = (t - t0) / dur
    if not 0 <= k <= 1: return
    r = np.random.default_rng(seed)
    m = np.zeros((H, W), np.float32)
    for _ in range(n):
        ang = r.uniform(0, 2 * math.pi); d = spread * r.uniform(0.35, 1) * ease_out(k)
        x, y = cx + d * math.cos(ang), cy + d * math.sin(ang) + 60 * k * k
        s = r.uniform(10, 22) * (1 - k)
        if s < 1: continue
        pts = [(x, y - s), (x + s * .22, y - s * .22), (x + s, y), (x + s * .22, y + s * .22), (x, y + s), (x - s * .22, y + s * .22), (x - s, y), (x - s * .22, y - s * .22)]
        cv2.fillPoly(m, [np.array(pts, np.int32)], 1.0, cv2.LINE_AA)
    glow = cv2.GaussianBlur(m, (0, 0), 6)
    add_layer(img, col, np.clip(glow * 1.2, 0, 1) * (1 - k), 'screen')
    add_layer(img, WHITE, m * (1 - k * 0.5))

def light_sweep(img, t, t0, rect, dur=0.55):
    k = (t - t0) / dur
    if not 0 <= k <= 1: return
    x0, y0, x1, y1 = rect
    band = (xx[y0:y1, x0:x1] - x0) - (yy[y0:y1, x0:x1] - y0) * 0.6
    pos = -150 + (x1 - x0 + 300) * ease_in_out(k)
    a = np.exp(-((band - pos) / 38) ** 2) * 0.55
    sub = img[y0:y1, x0:x1]
    sub[:] = 1 - (1 - sub) * (1 - a[..., None])

def glow_rect(img, rect, strength, col=WHITE, blur=28):
    if strength <= 0: return
    x0, y0, x1, y1 = rect
    m = np.zeros((H, W), np.float32)
    cv2.rectangle(m, (x0, y0), (x1, y1), 1.0, -1)
    g = cv2.GaussianBlur(m, (0, 0), blur) - m * 0.9
    add_layer(img, col, np.clip(g, 0, 1) * strength, 'screen')

def leak(t, cx, cy, rad, col, amp):
    g = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * rad ** 2)))
    return g * amp

# fumée de la fusée : particules pré-simulées
def rocket_path(k):
    """k 0..1 -> position (x, y) sortie et angle (degrés, sens horaire négatif)."""
    x0, y0, x1, y1 = 0.92 * W, 1.12 * H, 0.30 * W, -0.25 * H
    e = ease_in(k) * 0.75 + k * 0.25
    x = x0 + (x1 - x0) * e + 60 * math.sin(k * 3.2)
    y = y0 + (y1 - y0) * e
    return x, y

# ------------------------------------------------------------------ programme
def main():
    src, d3 = sys.argv[1], sys.argv[2]
    only = [int(v) for v in sys.argv[3].split(',')] if len(sys.argv) > 3 else None

    cap = cv2.VideoCapture(src); frames = []
    while True:
        ok, f = cap.read()
        if not ok: break
        frames.append(f)
    nsrc = len(frames)

    RIGHT = (0.79, 0.32, 0.34, 0.15)
    TOP = (0.50, 0.205, 0.66, 0.195)
    E = dict(
        houses=Element(d3, 'houses', 0.85, (0.50, 0.31, 0.70, 0.155)),
        play=Element(d3, 'play', 8.90, TOP),
        question=Element(d3, 'question', 13.30, (0.83, 0.34, 0.18, 0.13)),
        suitcase=Element(d3, 'suitcase', 16.20, RIGHT),
        coins=Element(d3, 'coins', 20.35, (0.80, 0.315, 0.32, 0.19)),
        cursor=Element(d3, 'cursor', 24.30, (0.80, 0.34, 0.16, 0.10)),
        gift=Element(d3, 'gift', 26.33, (0.80, 0.33, 0.30, 0.17)),
        gears=Element(d3, 'gears', 29.45, TOP),
        shield=Element(d3, 'shield', 32.55, (0.50, 0.195, 0.30, 0.15)),
        rocket=Element(d3, 'rocket', 34.25, (0.5, 0.5, 0.30, 0.26)),
        cursor_end=Element(d3, 'cursor', 35.55, (0.70, 0.735, 0.13, 0.085)),
    )
    E['rocket'].n = 10 ** 6   # la fusée boucle ses images, le vol est piloté ici
    BTN = (int(50 * S0 - OX), int(557 * S0), int(432 * S0 - OX), int(618 * S0))
    CLICK_END = src_to_out(35.55) + 24 / FPS
    CLICK_MAIN = E['cursor'].t0 + 24 / FPS
    GIFT_POP = E['gift'].t0 + 37 / FPS
    t_end = src_to_out(END_CARD)
    t_rocket0, t_rocket1 = src_to_out(34.25), src_to_out(35.12)

    # particules de fumée
    smoke = []
    pr = np.random.default_rng(5)
    for j in range(60):
        k = j / 60
        x, y = rocket_path(k)
        smoke.append((t_rocket0 + k * (t_rocket1 - t_rocket0), x + pr.normal(0, 10), y + 120 + pr.normal(0, 10), pr.uniform(18, 34)))

    out = sys.stdout.buffer
    rng_ = range(NFR) if only is None else only
    for fi in rng_:
        t = fi / FPS
        ts = out_to_src(t)
        si = min(nsrc - 1, int(round(ts * 30)))
        M = camera(t, ts)
        img = cv2.warpAffine(frames[si], M, (W, H), flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)
        img = img.astype(np.float32) / 255
        # netteté (la source est en 480p)
        blur = cv2.GaussianBlur(img, (0, 0), 1.6)
        img = np.clip(img + (img - blur) * 0.55, 0, 1)
        img = grade(img)

        # transitions sur les changements de plan : zoom-blur + petit flash
        for c in SHOT_CUTS + [b for a, b in KEEP[:-1]]:
            tc = src_to_out(c)
            if 0 <= t - tc < 0.14:
                k = (t - tc) / 0.14
                img = zoom_blur(img, 1 - k)
                img = np.clip(img + 0.10 * (1 - k), 0, 1)

        # lumière parasite chaude (hook + écran de fin)
        if t < 2.2:
            a = leak(t, W * (0.05 + 0.1 * t), H * 0.2, 420, None, 0.12 * (1 - ease_in(t / 2.2)))
            add_layer(img, WARM_WHITE, a, 'screen')
        if ts >= END_CARD:
            k = ts - END_CARD
            a = leak(t, W * (1.05 - 0.2 * k), H * 0.15, 480, None, 0.10)
            add_layer(img, WARM_WHITE, a, 'screen')

        # --- éléments 3D
        for key in ('houses', 'play', 'question', 'suitcase', 'coins', 'gift', 'gears', 'shield'):
            E[key].draw(img, t)
        # badges ✓ des maisons : étincelles vertes
        h = E['houses']
        for j in range(3):
            tb = h.t0 + (40 + 7 * j + 6) / FPS
            sparkles(img, t, tb, W * (0.5 + (j - 1) * 0.2 + 0.07), H * 0.285, n=8, spread=110, dur=0.5, seed=j)
        # compteur : étincelles quand il atteint 1 500
        sparkles(img, t, E['play'].t0 + 45 / FPS, W * 0.5, H * 0.24, n=16, spread=320, dur=0.8, seed=4)
        # curseur + clic
        i = E['cursor'].draw(img, t)
        if E['cursor'].frame(CLICK_MAIN) is not None:
            tx, ty = E['cursor'].tip(E['cursor'].frame(CLICK_MAIN))
            ring(img, t, CLICK_MAIN, tx, ty, WHITE, r_max=130)
        sparkles(img, t, GIFT_POP, W * 0.80, H * 0.30, n=18, spread=260, dur=0.9, seed=7)
        sparkles(img, t, E['shield'].t0 + 16 / FPS, W * 0.5, H * 0.20, n=14, spread=300, dur=0.8, seed=9)

        # fusée
        if t_rocket0 <= t <= t_rocket1 and E['rocket'].frames:
            for (t0, x, y, r0) in smoke:
                if t0 <= t:
                    age = t - t0; a = 0.55 * math.exp(-age * 2.2)
                    if a < 0.02: continue
                    m = np.zeros((H, W), np.float32)
                    cv2.circle(m, (int(x), int(y + age * 60)), int(r0 + age * 90), 1.0, -1, cv2.LINE_AA)
                    add_layer(img, (0.92, 0.92, 0.95), cv2.GaussianBlur(m, (0, 0), 14) * a)
            k = (t - t_rocket0) / (t_rocket1 - t_rocket0)
            x, y = rocket_path(k)
            el = E['rocket']; fidx = int((t - t_rocket0) * FPS) % len(el.frames)
            f, sh, pad = el.get(fidx)
            x2, y2 = rocket_path(min(1, k + 0.02))
            ang = math.degrees(math.atan2(x2 - x, -(y2 - y)))
            hh, ww = f.shape[:2]
            R = cv2.getRotationMatrix2D((ww / 2, hh / 2), -ang, 1.0)
            cosr, sinr = abs(R[0, 0]), abs(R[0, 1])
            nw, nh = int(hh * sinr + ww * cosr), int(hh * cosr + ww * sinr)
            R[0, 2] += nw / 2 - ww / 2; R[1, 2] += nh / 2 - hh / 2
            fr = cv2.warpAffine(f, R, (nw, nh), flags=cv2.INTER_LINEAR)
            alpha_over(img, fr, int(x - nw / 2), int(y - nh / 2))

        # écran de fin : flash, halo et reflet sur le bouton, clic
        if ts >= END_CARD:
            k = ts - END_CARD
            glow_rect(img, BTN, 0.30 + 0.18 * math.sin(k * 5.5))
            light_sweep(img, t, t_end + 0.35, BTN)
            light_sweep(img, t, t_end + 1.45, BTN)
            E['cursor_end'].draw(img, t)
            ic = E['cursor_end'].frame(CLICK_END)
            if ic is not None:
                tx, ty = E['cursor_end'].tip(ic)
                ring(img, t, CLICK_END, tx, ty, WHITE, r_max=170)
        if 0 <= t - t_end < 0.22:
            k = (t - t_end) / 0.22
            a = (1 - ease_out(k))
            # aberration chromatique + flash blanc
            sh_px = int(18 * a)
            if sh_px:
                img[..., 2] = np.roll(img[..., 2], sh_px, 1); img[..., 0] = np.roll(img[..., 0], -sh_px, 1)
            img = np.clip(img + 0.5 * a, 0, 1)
        # fondu au noir des 6 dernières images
        if t > DUR_OUT - 0.2:
            img *= clamp((DUR_OUT - t) / 0.2)

        img = img * VIGNETTE + GRAIN[fi % len(GRAIN)]
        out.write((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes())
        if fi % 60 == 0: print('frame', fi, '/', NFR, file=sys.stderr, flush=True)

if __name__ == '__main__':
    main()
