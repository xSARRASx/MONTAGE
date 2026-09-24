# MONTAGE — Vidéo Masterclass conciergerie (verticale 9:16)

## Version 3 — style sobre (recommandée) : `output/montage_sobre.mp4`

Inspirée du *principe* de la vidéo de référence (épuré, beige / blanc papier / vert sauge, cartes plein écran,
3D discrète) mais avec des idées différentes :

- **Visage dans un cadre arrondi** sur fond beige, recadré juste au-dessus des anciens sous-titres incrustés
  (qui disparaissent), avec des pastilles vertes : « 10 ans d'accompagnement », « Location courte durée »,
  « Clique autour de la vidéo », « Résultats garantis ».
- **Cartes plein écran** pendant les anciens bandeaux orange/bleu (qui sont ainsi masqués) :
  | Moment | Carte |
  |---|---|
  | « 3 propriétaires signés… 6 mois » | 3 contrats 3D qui se posent, signature qui s'écrit, tampon vert « signé » + frise M1→M6 |
  | « Pierre… mon père… 4 ans » | « Pierre & son père. » + chiffres clés « 4 ans » / « +10 ans » |
  | « 1 500 vidéos sur YouTube » | compteur 0 → 1 500 + mosaïque de vignettes |
  | « La conciergerie c'est quoi ? … accompagner » | « C'est quoi ? » → « Accompagner des propriétaires. » + maison 3D épurée |
  | « 20 et 25 % de commissions » | compteur « 20 à 25 % » + bloc 3D « revenu locatif » dont le quart vert se détache |
  | « Masterclass 100 % gratuite… » | carte sombre, visuel de la masterclass, checklist qui se coche |
  | Fin | « Lance ta conciergerie. » + bouton « VOIR LA MASTERCLASS » |
- **Sous-titres** refaits (police Manrope), un mot-clé en vert par phrase.
- **Son** : musique douce (piano électrique), effets discrets, voix nettoyée, −14 LUFS.

Reconstruire : `./build_sobre.sh <video_source.mp4> <dossier_travail>`
(`src/render3d_sobre.py`, `src/composite_sobre.py`, `src/audio_sobre.py`).

---

## Version 2 — 3D noir + or : `output/montage_final.mp4`
Vidéo : `output/montage_final.mp4` (1080×1920, 30 i/s, H.264 + AAC, −14 LUFS, ~36,5 s, < 30 Mo).

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
