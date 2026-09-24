# MONTAGE — Vidéo Masterclass conciergerie (verticale 9:16)

Vidéo finale : `output/montage_final.mp4` (1080×1920, 30 i/s, H.264 + AAC, −14 LUFS, ~36,5 s, < 30 Mo).

## Ce qui a été fait

- **Rythme** : suppression des blancs entre les phrases (≈0,7 s au total), transitions « zoom-blur » sur chaque coupe. Aucune phrase répétée n'a été trouvée dans l'audio (transcription complète vérifiée mot à mot).
- **Upscale 1080×1920** depuis la source 480×848 (Lanczos + accentuation).
- **Caméra dynamique** : push-in lents, cadrage alterné à chaque plan, punch-in sur les mots-clés (« 3 », « 10 ans », « 1 500 », « quoi », « 20 / 25 % », « cliquer », « 100 % », « garantir », « lancement »), secousses sur les impacts.
- **Étalonnage** : neutre (aucun virage orange/bleu), contraste doux en S, légère saturation, vignettage, grain cinéma.
- **10 éléments 3D animés** (Blender Cycles), en palette sobre **noir laqué + or** pour ne pas surcharger l'orange/bleu des bandeaux déjà incrustés, et placés dans les zones libres pour ne jamais masquer les bandeaux et sous-titres :
  | Moment | Élément |
  |---|---|
  | « 3 propriétaires signés » | 3 maisons qui tombent avec rebond + badges ✓ dorés |
  | « 10 ans… 1 500 vidéos sur YouTube » | bouton lecture 3D + compteur de 0 à +1 500 |
  | « c'est quoi ? » | point d'interrogation 3D qui tourne |
  | « location courte durée » | valise + clé dorée en orbite |
  | « 20 et 25 % de commissions » | pile de pièces d'or qui tombent + « % » 3D |
  | « cliquer autour de cette vidéo » | curseur 3D qui clique (onde de clic) |
  | « Masterclass 100 % gratuite » | cadeau qui s'ouvre + « GRATUIT » |
  | « comment ton activité peut fonctionner » | engrenages qui s'emboîtent |
  | « garantir des résultats » | bouclier avec coche |
  | « nouveau lancement » | fusée qui traverse l'écran avec traînée de fumée |
  | Écran de fin | flash + aberration chromatique, halo blanc et reflet lumineux sur « VOIR LA VIDÉO », curseur 3D qui clique |
- **Sound design** (100 % synthétisé, libre de droits) : whooshs, impacts, pops, dings, tics, caisse enregistreuse, riser, plus une musique électro-pop discrète avec ducking automatique sous la voix, qui remonte sur l'écran de fin.
- **Voix** : passe-haut, EQ (boue −2 dB, présence +3 dB, air +2 dB), compression, normalisation à −14 LUFS (standard réseaux sociaux).

## Reconstruire

```bash
apt-get install ffmpeg fonts-roboto
pip install bpy opencv-python-headless numpy pillow
./build.sh <video_source.mp4> <dossier_travail>
```

- `src/render3d.py` — modélisation, animation et rendu 3D (bpy / Cycles).
- `src/composite.py` — montage, caméra, étalonnage, compositing 3D et 2D.
- `src/audio.py` — mixage voix / musique / effets sonores.
- `src/sfx.py` — synthèse des effets sonores et de la musique.
