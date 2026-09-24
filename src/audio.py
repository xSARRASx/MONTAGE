"""Mixage audio : voix nettoyée (coupes avec micro-fondus) + musique « ducking » + sound design."""
import sys, wave, numpy as np
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from composite import KEEP, src_to_out, DUR_OUT, END_CARD, FPS

SR = 44100
def load(p):
    with wave.open(p) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(np.float32) / 32768
        return x.reshape(-1, w.getnchannels())

def main(voice_wav, sfx_dir, out_wav):
    v = load(voice_wav)
    fade = int(0.012 * SR)
    parts = []
    for a, b in KEEP:
        p = v[int(a * SR):int(b * SR)].copy()
        ramp = np.linspace(0, 1, fade)[:, None]
        p[:fade] *= ramp; p[-fade:] *= ramp[::-1]
        parts.append(p)
    voice = np.concatenate(parts)
    N = int(DUR_OUT * SR) + SR
    mix = np.zeros((N, 2), np.float32); mix[:len(voice)] += voice

    # enveloppe de la voix -> ducking de la musique
    env = np.abs(voice.mean(1)); k = int(0.25 * SR)
    env = np.convolve(env, np.ones(k) / k, 'same')
    env = np.pad(env, (0, N - len(env)))
    duck = np.clip(env / (env.max() * 0.25), 0, 1)
    music = load(f'{sfx_dir}/music.wav')[:N]
    music = np.pad(music, ((0, N - len(music)), (0, 0)))
    t = np.arange(N) / SR
    t_end = src_to_out(END_CARD)
    gain = 0.11 * (1 - 0.55 * duck)
    gain = np.where(t >= t_end, 0.30, gain)
    gain *= np.clip(t / 0.3, 0, 1) * np.clip((DUR_OUT - t) / 0.8, 0, 1)
    mix += music * gain[:, None]

    def put(name, ts, g, src_time=True):
        x = load(f'{sfx_dir}/{name}.wav')
        s = int((src_to_out(ts) if src_time else ts) * SR)
        e = min(N, s + len(x))
        if s < N: mix[s:e] += x[:e - s] * g

    fr = lambda start_src, f: src_to_out(start_src) + f / FPS
    # hook
    put('impact', 0.0, 0.35); put('whoosh', 0.75, 0.25)
    for i, st in enumerate((1, 9, 17)): put('pop', fr(0.85, st + 6), 0.4, False)
    for j in range(3): put('pop_hi', fr(0.85, 40 + 7 * j + 2), 0.3, False)
    put('impact', 0.96, 0.45)
    # transitions sur les coupes
    for c in (4.37, 11.93, 18.47, 23.73): put('whoosh_dn', c - 0.2, 0.22)
    # 1 500 vidéos
    put('whoosh', 8.85, 0.3)
    for f in range(22, 46, 2): put('tick', fr(8.90, f), 0.18, False)
    put('ding', fr(8.90, 45), 0.3, False)
    put('pop', 13.3, 0.4)                       # ?
    put('whoosh', 16.1, 0.25)                    # valise
    for i in range(8): put('tick', fr(20.35, 1 + i * 3 + 5), 0.3, False)   # pièces
    put('cash', fr(20.35, 20), 0.35, False)
    put('pop', fr(20.35, 30), 0.4, False)        # %
    put('whoosh', 24.2, 0.2); put('tick', fr(24.30, 24), 0.6, False); put('pop_hi', fr(24.30, 24), 0.3, False)
    put('whoosh', 26.3, 0.2); put('pop', fr(26.33, 37), 0.45, False); put('ding', fr(26.33, 38), 0.3, False)
    put('whoosh', 29.4, 0.25)
    put('impact', 32.55, 0.25); put('ding', fr(32.55, 16), 0.28, False)
    put('riser', 33.6, 0.3); put('whoosh', 34.3, 0.4)
    put('impact', END_CARD, 0.55)
    put('tick', fr(35.55, 24), 0.6, False); put('pop_hi', fr(35.55, 24), 0.3, False)

    mix = mix[:int(DUR_OUT * SR)]
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)
    with wave.open(out_wav, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype('<i2').tobytes())

if __name__ == '__main__':
    main(*sys.argv[1:4])
