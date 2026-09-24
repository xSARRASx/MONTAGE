# MONTAGE — Vidéo Masterclass conciergerie (verticale 9:16)

## Version 8 — la plus aboutie (recommandée) : `output/montage_v8.mp4`

Tout ce qui est décrit en version 7, plus :
- **Sous-titres des plans de Pierre dans des pastilles sombres arrondies**, posées exactement sur l'emplacement et la
  taille de l'ancienne boîte (une ou deux lignes). Là où l'ancien sous-titre cachait déjà le bas de la bouche dans le
  rush, plus rien n'est flouté ni inventé : bouche et menton propres sur toute la vidéo.
- Checklist de la masterclass lisible (chaque point reste au moins 1 s), « masterclass » écrit partout pareil.

## Version 7 : `output/montage_v7.mp4`

Tout ce qui est décrit en version 6, plus :
- **Sébastien MORE en vraie vidéo** sur l'écran de l'ordinateur (extraits de son compte TikTok « moresebastien »,
  sans texte ni son, `assets/videos/`), façon lecteur de cours.
- **Pierre à l'écran sur « Moi c'est Pierre… »**, avec son prénom en surimpression, avant la carte « Pierre & son père ».
- Effacement des anciens sous-titres adouci : ombre douce sous les nouveaux sous-titres, pile sur la zone effacée.
- Sous-titres dans le style de la scène dominante pendant les transitions ; écran de fin sans barre grise.

## Version 6 — images réelles : `output/montage_v6.mp4`

- **Vraies photos** à la place de la 3D après la carte YouTube : remise de clés (conciergerie),
  maison en bois + calculatrice (commission 20 à 25 %), ordinateur sur un bureau (masterclass, écran de fin).
- **Sébastien MORE à l'écran de l'ordinateur** (image tirée de ses miniatures YouTube), façon vidéo de cours.
- **Logos Airbnb et Booking.com** (officiels, Wikimedia Commons) quand Pierre parle d'Airbnb et de location courte durée.
- **Plus de Pierre à la fin** : plan plein écran sur « location courte durée » (plus de lit) et de « qui t'explique… » jusqu'à la fin.
- Corrections issues de la revue qualité : effacement des anciens sous-titres beaucoup plus précis (bouche et
  tee-shirt nets), sous-titres affichés une seule fois pendant les transitions, plus aucun reste d'ancien bandeau,
  typographie française (« 25 % », « location courte durée »).

### Crédits photos (Licence Unsplash, usage commercial gratuit)
- Remise de clés : Jakub Żerdzicki — https://unsplash.com/photos/holding-house-keys-in-front-of-the-entrance-bqUZEAeWuok
- Maison en bois et calculatrice : Sasun Bughdaryan — https://unsplash.com/photos/model-house-with-calculator-and-pen-on-desk-jkO_wMw4168
- Ordinateur sur bureau : Paulina Chmolowska — https://unsplash.com/photos/macbook-pro-on-brown-wooden-table-kBtuVD25HAA

---

## Version 4 — au plus proche de la référence (recommandée) : `output/montage_v4.mp4`

- **Visage plein écran** : les anciens sous-titres, la barre de progression et le logo sont effacés
  (reconstruction de l'image + léger zoom), comme dans la vidéo de référence.
- **Sous-titres blancs** posés sur la vidéo, ombre douce, un mot-clé en vert clair.
- **Fond photo** : chambre photoréaliste rendue en 3D (lit, oreillers, rideaux voilés, lumière du jour)
  pour « Location courte durée » et l'écran de fin (« Ta conciergerie. Lance-toi. » + bouton).
- Cartes beige et 3D de la version 3 (contrats signés, maison, bloc 25 %, masterclass sombre).

Scripts : `src/composite_ref.py`, `src/render_chambre.py`, `src/audio_sobre.py` (avec `SANS_PASTILLES=1`).

---

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
