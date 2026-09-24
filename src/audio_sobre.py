"""Mixage audio du style sobre : voix + musique douce (ducking) + quelques effets discrets."""
import sys, os, wave, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from composite import KEEP, src_to_out
from composite_sobre import SCENES, DUR, T_END
from audio import load

SR = 44100

def main(voice_wav, sfx_dir, out_wav):
    v = load(voice_wav); fade = int(0.012 * SR); parts = []
    for a, b in KEEP:
        p = v[int(a * SR):int(min(b, 35.2) * SR)].copy()
        if len(p) < 2 * fade: continue
        r = np.linspace(0, 1, fade)[:, None]; p[:fade] *= r; p[-fade:] *= r[::-1]; parts.append(p)
    voice = np.concatenate(parts)
    N = int(DUR * SR); mix = np.zeros((N, 2), np.float32)
    voice = voice[:N]; mix[:len(voice)] += voice
    env = np.abs(voice.mean(1)); k = int(0.3 * SR)
    env = np.pad(np.convolve(env, np.ones(k) / k, 'same'), (0, N - len(voice)))
    duck = np.clip(env / (env.max() * 0.25), 0, 1)
    music = load(f'{sfx_dir}/music_soft.wav')[:N]; music = np.pad(music, ((0, N - len(music)), (0, 0)))
    t = np.arange(N) / SR
    gain = np.where(t >= T_END, 0.34, 0.16 * (1 - 0.5 * duck))
    gain *= np.clip(t / 0.4, 0, 1) * np.clip((DUR - t) / 1.2, 0, 1)
    mix += music * gain[:, None]
    def put(name, t_out, g):
        x = load(f'{sfx_dir}/{name}.wav'); s = int(t_out * SR); e = min(N, s + len(x))
        if 0 <= s < N: mix[s:e] += x[:e - s] * g
    for kind, a, b in SCENES[1:]:
        put('whoosh_soft', src_to_out(a) - 0.12, 0.10)
    o = src_to_out
    for i in range(3): put('pop', o(0.95) + (58 + 7 * i) / 30, 0.16)                  # tampons « signé »
    if not os.environ.get('SANS_PASTILLES'):
        for x in (9.15, 16.6, 24.98, 32.74): put('pop_hi', o(x), 0.12)               # pastilles (version 3)
    for x in (29.85, 30.45, 31.05): put('pop_hi', o(x), 0.10)                         # checklist
    for f in range(0, 26, 3): put('tick', o(9.95) + f / 30, 0.08)                     # compteur vidéos
    put('ding', o(10.8), 0.10); put('ding', T_END + 0.1, 0.12)
    mix = np.tanh(mix * 1.05) / np.tanh(1.05)
    with wave.open(out_wav, 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(mix, -1, 1) * 32767).astype('<i2').tobytes())

if __name__ == '__main__':
    main(*sys.argv[1:4])
