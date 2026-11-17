# Héritage en Champagne — règles du projet

Source de vérité : `docs/GDD.md` (à relire avant chaque étape).
Utilisateur : Alexis, non développeur, travaille depuis son téléphone. Expliquer simplement, en français.

## Règles
- **Langue** : tout texte du jeu est en français. Ton chaleureux, précis, jamais moralisateur ; on parle du métier, pas de consommation d'alcool.
- **Stack** : TypeScript + Vite + Three.js. Publication GitHub Pages (`base` Vite = `./`).
- **Séparation stricte** : la simulation vit dans `src/sim/` (TypeScript pur, aucun import de Three.js ni du DOM). L'affichage ne contient aucune règle de jeu.
- **Chiffres d'équilibrage** : uniquement dans `src/data/*.json`, jamais en dur dans le code. Textes éducatifs dans `src/data/textes.json`.
- **Priorité téléphone** : paysage d'abord, portrait supporté, monde 3D ≥ 75 % de l'écran, texte ≥ 15 px, boutons ≥ 44 px, barre du haut ≤ 40 px.
- **Tests obligatoires** : Vitest pour chaque règle de `src/sim/` (`npm test`).
- **Captures Playwright** après chaque changement d'interface : 360×800, 390×844, 768×1024, 1280×720, paysage et portrait. Regarder les images et corriger avant de rendre la main.
- **Performance** : 30 images/s mini sur Android milieu de gamme, chargement < 15 Mo.
- **Licences** : chaque modèle 3D / son listé avec sa licence dans `docs/CREDITS.md`.
- Tous les textes éducatifs sont relus par Alexis avant publication.

## Commandes
- `npm run dev` : serveur local · `npm run build` : build · `npm test` : tests Vitest · `npm run typecheck`
