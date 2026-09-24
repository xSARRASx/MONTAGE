"""Synthèse des effets sonores et de la musique (aucun asset externe, donc libre de droits)."""
import numpy as np, wave, sys, os
SR = 44100
rng = np.random.default_rng(7)

def save(path, x):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1: x = np.stack([x, x], 1)
    x = x / max(1e-9, np.abs(x).max()) * 0.95
    with wave.open(path, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype('<i2').tobytes())

def t_(d): return np.arange(int(d * SR)) / SR

def lp(x, fc):  # simple one-pole low-pass, fc can be array
    fc = np.broadcast_to(fc, x.shape)
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.empty_like(x); s = 0.0
    for i in range(len(x)):
        s = (1 - a[i]) * x[i] + a[i] * s; y[i] = s
    return y

def whoosh(d=0.7, up=True):
    t = t_(d); n = rng.standard_normal(len(t))
    env = np.sin(np.pi * t / d) ** 2
    fc = 300 + 5000 * (t / d if up else 1 - t / d) ** 1.5
    x = lp(lp(n, fc), fc) * env
    pan = np.linspace(-0.7, 0.7, len(t))
    return np.stack([x * (1 - pan) / 2, x * (1 + pan) / 2], 1)

def impact(d=1.2):
    t = t_(d)
    f = 110 * np.exp(-t * 6) + 38
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3.2)
    click = lp(rng.standard_normal(len(t)), 2500) * np.exp(-t * 40)
    return body + 0.6 * click

def pop(f0=900):
    t = t_(0.18)
    f = f0 * (1 + 1.5 * np.exp(-t * 50))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 28)

def ding():
    t = t_(1.2)
    return sum(a * np.sin(2 * np.pi * f * t) * np.exp(-t * k)
               for f, a, k in [(1318.5, 1, 3), (2637, .35, 5), (1975.5, .3, 4), (3951, .12, 7)])

def riser(d=1.5):
    t = t_(d); n = rng.standard_normal(len(t))
    fc = 200 + 7000 * (t / d) ** 2
    tone = np.sin(2 * np.pi * np.cumsum(200 + 600 * (t / d) ** 2) / SR)
    return (lp(n, fc) * 0.7 + 0.3 * tone) * (t / d) ** 2

def tick():
    t = t_(0.04)
    return lp(rng.standard_normal(len(t)), 6000) * np.exp(-t * 150)

def cash():
    x = np.concatenate([ding()[:int(.5 * SR)] * 0.8, np.zeros(1)])
    t = t_(0.5)
    coins = sum(np.sin(2 * np.pi * f * t) * np.exp(-t * 12) * (t > s) for f, s in [(3200, 0), (4100, .05), (3700, .1), (4500, .16)])
    return x[:len(t)] + 0.4 * coins

def music(dur, bpm=112):
    """Nappe électro-pop discrète : kick, hats, basse, accords. Mixée très bas sous la voix."""
    N = int(dur * SR); out = np.zeros((N, 2)); beat = 60 / bpm
    chords = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]  # Am F C G
    m2f = lambda m: 440 * 2 ** ((m - 69) / 12)
    kick_t = t_(0.35); kick = np.sin(2 * np.pi * np.cumsum(50 + 120 * np.exp(-kick_t * 30)) / SR) * np.exp(-kick_t * 9)
    hat_t = t_(0.06); hat = rng.standard_normal(len(hat_t)); hat = (hat - lp(hat, 7000)) * np.exp(-hat_t * 70)
    nb = int(dur / beat) + 1
    for b in range(nb):
        s = int(b * beat * SR)
        def add(sig, gain, pan=0.0, start=s):
            e = min(N, start + len(sig))
            if start >= N: return
            out[start:e, 0] += sig[:e - start] * gain * (1 - pan)
            out[start:e, 1] += sig[:e - start] * gain * (1 + pan)
        add(kick, 0.9)
        add(hat, 0.25, 0.3, s + int(beat / 2 * SR))
        if b % 2 == 1: add(hat, 0.15, -0.3)
        bar = (b // 4) % 4
        root = m2f(chords[bar][0] - 24)
        bt = t_(beat * 0.9)
        bass = np.tanh(2 * np.sin(2 * np.pi * root * bt)) * np.exp(-bt * 2.5)
        add(bass, 0.35)
        if b % 4 == 0:
            ct = t_(beat * 4)
            pad = sum(np.sin(2 * np.pi * m2f(m) * ct + 0.3 * np.sin(2 * np.pi * 5 * ct)) for m in chords[bar])
            pad *= np.minimum(1, ct / 0.3) * np.exp(-ct * 0.4)
            add(pad, 0.12, 0.0)
    return out

def music_soft(dur, bpm=86):
    """Musique douce : accords de piano électrique chauds, basse ronde, pulsation très légère (style épuré)."""
    N = int(dur * SR); out = np.zeros((N, 2)); beat = 60 / bpm
    chords = [[57, 60, 64, 67, 71], [53, 57, 60, 64, 67], [48, 52, 55, 59, 64], [55, 59, 62, 66, 69]]  # Am9 Fmaj9 Cmaj7 G6
    m2f = lambda m: 440 * 2 ** ((m - 69) / 12)
    def ep(f, d):
        t = t_(d)
        x = np.sin(2 * np.pi * f * t + 0.8 * np.sin(2 * np.pi * f * t) * np.exp(-t * 4))
        x += 0.25 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 3)
        return x * np.exp(-t * 1.1) * np.minimum(1, t / 0.008)
    def add(sig, gain, start, pan=0.0):
        if start >= N: return
        e = min(N, start + len(sig))
        out[start:e, 0] += sig[:e - start] * gain * (1 - pan); out[start:e, 1] += sig[:e - start] * gain * (1 + pan)
    nbars = int(dur / (beat * 4)) + 1
    for bar in range(nbars):
        s0 = int(bar * 4 * beat * SR); ch = chords[bar % 4]
        for j, m in enumerate(ch):                       # accord légèrement arpégé
            add(ep(m2f(m), beat * 4.2), 0.16, s0 + int(j * 0.018 * SR), (j - 2) * 0.12)
        for j, off in enumerate((2.5, 3.5)):              # petits rappels
            add(ep(m2f(ch[-1 - j] + 12), beat * 1.5), 0.05, s0 + int(off * beat * SR), 0.3 - 0.6 * j)
        bt = t_(beat * 3.8); f0 = m2f(ch[0] - 24)
        add(np.sin(2 * np.pi * f0 * bt) * np.exp(-bt * 0.9) * np.minimum(1, bt / 0.02), 0.32, s0)
        for k in range(4):                                # pulsation feutrée
            kt = t_(0.25)
            add(np.sin(2 * np.pi * np.cumsum(45 + 60 * np.exp(-kt * 25)) / SR) * np.exp(-kt * 14), 0.25, s0 + int(k * beat * SR))
            ht = t_(0.05); hh = rng.standard_normal(len(ht)); hh = (hh - lp(hh, 8000)) * np.exp(-ht * 90)
            add(hh, 0.035, s0 + int((k + 0.5) * beat * SR), 0.25)
    return out

def whoosh_soft(d=0.45):
    t = t_(d); n = rng.standard_normal(len(t))
    env = np.sin(np.pi * t / d) ** 3
    x = lp(lp(n, 400 + 2200 * t / d), 2500) * env
    return x

if __name__ == '__main__':
    d = sys.argv[1]; os.makedirs(d, exist_ok=True)
    save(f'{d}/whoosh.wav', whoosh()); save(f'{d}/whoosh_dn.wav', whoosh(0.5, False))
    save(f'{d}/impact.wav', impact()); save(f'{d}/pop.wav', pop()); save(f'{d}/pop_hi.wav', pop(1400))
    save(f'{d}/ding.wav', ding()); save(f'{d}/riser.wav', riser()); save(f'{d}/tick.wav', tick())
    save(f'{d}/cash.wav', cash()); save(f'{d}/music.wav', music(float(sys.argv[2])))
    save(f'{d}/music_soft.wav', music_soft(float(sys.argv[2]))); save(f'{d}/whoosh_soft.wav', whoosh_soft())
