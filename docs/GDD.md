# Héritage en Champagne — Document de conception (GDD)

Jeu de gestion en 3D : le joueur reprend les 2 ha de vigne de ses parents, livreurs de raisins pour une grande maison, et en fait une maison de champagne. Il apprend le vrai métier en le faisant : chaque geste du vigneron et du chef de cave est expliqué.

- **Public** : grand public curieux de champagne, clients du bar à champagne mobile, amateurs de jeux de gestion. Aucune connaissance nécessaire.
- **Plateformes** : téléphone et tablette d'abord (paysage et portrait), ordinateur ensuite. Jeu web, sans installation.
- **Rythme** : lent et posé. Un mois de jeu dure 3 à 6 minutes, une année environ 45 minutes. Le temps n'avance jamais tout seul.
- **Promesse** : se sentir en Champagne (coteaux, craie, village, saisons) et repartir en sachant comment on fait une bouteille.
- **Deux modes** : la partie complète, mois par mois, sauvegardée ; puis plus tard un mode « Défi du bar » de 10 minutes avec classement, pour les événements.
- **Ton** : chaleureux, précis, jamais moralisateur. On parle du métier, pas de consommation d'alcool.

## Choix techniques

Projet web TypeScript + Three.js, publié sur GitHub Pages. Règle d'or : la simulation (règles, chiffres) est totalement séparée de l'affichage 3D, pour pouvoir la tester et l'équilibrer sans écran.

| Sujet | Choix | Pourquoi |
|---|---|---|
| Moteur 3D | Three.js installé par npm | Tourne dans tout navigateur de téléphone |
| Langage et outil | TypeScript + Vite | Erreurs détectées avant de jouer, build rapide |
| Modèles 3D | glTF low-poly libres de droits (Kenney, Quaternius, Poly Pizza), licence vérifiée une par une | Vrais bâtiments, arbres, personnages au lieu de cubes |
| Simulation | Module `src/sim/` en TypeScript pur, sans Three.js | Testable en ligne de commande |
| Chiffres d'équilibrage | Fichiers `src/data/*.json` | On règle le jeu sans toucher au code |
| Tests | Vitest pour la simulation, Playwright pour captures d'écran à plusieurs tailles de téléphone | Claude Code voit l'écran et corrige lui-même |
| Sauvegarde | localStorage + code d'export à copier | Reprendre sa partie, changer d'appareil |
| Publication | GitHub Pages, à chaque étape validée | Un lien à ouvrir sur le téléphone |

Performance : 30 images/s minimum sur un Android milieu de gamme, chargement initial < 15 Mo, premier écran < 5 s en 4G.

## Univers, carte et graphismes

Village fictif de **Saint-Aubin-les-Craies**, vallée de la Marne : coteaux plein sud couverts de rangs de vigne, forêt au sommet, craie blanche dans les chemins, clocher d'ardoise, la Marne en contrebas.

| Lieu | Rôle | Moments forts |
|---|---|---|
| Maison familiale | Bureau : clients, prix public, marque, chef de culture, missions | Toute l'année |
| Les Crayères (0,7 ha, chardonnay) | Parcelle héritée | Taille à vendanges |
| Le Mont Benoît (0,8 ha, pinot noir) | Parcelle héritée | Taille à vendanges |
| Les Hautes Vignes (0,5 ha, meunier) | Parcelle héritée | Taille à vendanges |
| Les Longues Raies (1 ha, pinot noir) | Parcelle à louer en fermage | Dès l'an 1 |
| Le Clos du Moulin (0,6 ha, chardonnay) | Parcelle à acheter | Fin de partie |
| Pressoir | Pressurage, vente des raisins au négoce | Septembre, octobre |
| Cave et cuverie (dans la craie) | Vins clairs, assemblage, tirage, lattes, dégorgement | Toute l'année |
| Maison Delaunay & Fils (château) | Grande maison : contrat raisins, rachat sur lattes | Toute l'année |
| Notaire et banque | Emprunts, fermage, achat de vignes, succession, bilan | Toute l'année |
| Église Saint-Vincent | Histoire et culture : Dom Pérignon, saint Vincent, la craie | Janvier (fête) |
| Loge de vigne | Cabane dans les vignes, point de vue et quiz | Toute l'année |

**Style** : low-poly chaleureux et soigné, lumière douce, ombres, brume légère au loin. Pas de réalisme photo.

**Saisons visibles** : vigne nue et sol pâle en hiver, givre les matins de gel, jeunes feuilles vert clair en avril, haies vertes en été, grappes vertes puis noires ou dorées, cueilleurs en septembre, feuilles jaunes et rousses en octobre-novembre. Pluie, orage et grêle s'affichent quand ils arrivent.

**Vie du village** : quelques habitants qui marchent, un tracteur enjambeur, des oiseaux, cloches à midi. Sons d'ambiance doux, coupables d'un bouton.

## Interface et contrôles mobile

Le monde 3D occupe au moins 75 % de l'écran, deux pouces libres. (Le prototype échouait : interface envahissante, joystick mal placé, panneaux qui cachaient tout.)

- **Orientation** : paysage en priorité, portrait supporté. Zones sûres respectées.
- **Barre du haut** : une seule ligne, 40 px max : date, jours de travail restants, trésorerie. Le reste (carte, missions, carnet, réglages) dans un bouton menu.
- **Joystick dynamique** : apparaît où le pouce gauche touche, quart bas gauche. Diamètre 110 px, invisible au repos.
- **Caméra** : glisser dans la moitié droite pour tourner, pincer pour zoomer, double tap pour recentrer.
- **Bouton d'action** : rond de 72 px en bas à droite, icône + nom court du lieu. N'apparaît que près d'un lieu.
- **Panneaux** : paysage = panneau latéral droit 40 % de la largeur ; portrait = tiroir du bas 60 % max. Le monde reste visible, le jeu en pause.
- **Mini-carte** : en haut à droite ; un tap ouvre la carte plein écran avec déplacement rapide.
- **Notifications** : une seule à la fois, en bas, 3 s. Les pages du carnet ne bloquent jamais : une icône clignote.
- **Lisibilité** : texte 15 px min, boutons 44 px min, contraste fort.
- **Vérification** : captures automatiques à 360×800, 390×844, 768×1024 et 1280×720, paysage et portrait, à chaque changement d'interface.

## Boucle de jeu et calendrier

Un tour = un mois. 10 jours de travail par mois (16 avec un chef de culture). Le joueur se déplace, travaille, puis appuie sur « Fin du mois ». Les jours non utilisés sont perdus.

Fin de mois, dans l'ordre : pénalités des travaux oubliés, météo et maladies, vieillissement des bouteilles, ventes directes, charges, nouvelles offres de clients, écran de résumé (ce qui s'est passé, comptes, ce qui arrive en Champagne le mois suivant). Le 31 décembre s'ajoutent impôts, droits de succession et bilan annuel.

| Mois | Vignes | Cave | Commerce | Risques |
|---|---|---|---|---|
| Janvier | Taille | Assemblage, tirage | Calme | – |
| Février | Taille | Assemblage, tirage | Calme | – |
| Mars | Fin de taille, liage | Tirage | Inscription au concours | – |
| Avril | Liage, protection | Tirage | Mariages | Gel |
| Mai | Ébourgeonnage, protection | Tirage | Résultats du concours | Mildiou |
| Juin | Palissage, protection | Fin des tirages, reste en réserve | Mariages | Coulure, mildiou |
| Juillet | Palissage, rognage, protection | Dégorgement | Été, tourisme | Grêle, oïdium |
| Août | Protection, véraison | Dégorgement | Ban des vendanges, prix du raisin | Grêle, canicule |
| Septembre | Vendanges | Pressurage, débourbage | Vente des raisins | Raisins non cueillis perdus |
| Octobre | Labour | Fermentations, malolactique | Commandes de fin d'année | Raisins non pressés bradés |
| Novembre | Buttage | Dégorgement pour les fêtes | Comités d'entreprise | – |
| Décembre | Repos | Dégorgement | Pic des ventes (x 2,8) | Rupture de stock |

## Règles du métier

Règles réelles simplifiées. Les chiffres sont des valeurs de départ, à ajuster par simulation.

### Vigne

Chaque travail se fait soi-même (jours) ou par une équipe (euros). Trois jauges par parcelle : santé (0-100, saison), qualité des raisins (année), qualité des souches (long terme, +2 par an si bien soignée, -2 sinon).

| Travail | Mois | Jours/ha | Équipe/ha | Si oublié |
|---|---|---|---|---|
| Taille (choix du système) | Janv.–mars | 5 | 3 500 € | Récolte -30 %, qualité -5 |
| Liage | Mars, avril | 2 | 1 200 € | Santé -6 |
| Protection du vignoble | Chaque mois avril–août | 1 | 600 € | Risque de maladie 45 % au lieu de 5 % |
| Ébourgeonnage | Mai | 3 | 1 800 € | Qualité -4, santé -5 |
| Palissage | Juin, juillet | 3 | 1 800 € | Santé -8, qualité -2 |
| Rognage | Juillet | 1 | 700 € | Qualité -2 |
| Vendanges (cueilleurs) | Septembre | 1 | 0,90 €/kg, payé en fin de mois | Raisins perdus |
| Labour et buttage | Oct., nov. | 2 | 900 € | Santé -4 |

Taille : quatre systèmes autorisés. Le système idéal donne +3 de qualité : Chablis (chardonnay), Cordon de Royat (pinot noir), Vallée de la Marne (meunier). Vallée de la Marne interdit sur les autres cépages. Guyot et Cordon acceptés partout.

Récolte = hectares × 11 500 kg × effets météo × (0,6 + 0,4 × santé / 100), plafonnée au rendement autorisé annoncé en août (10 000 à 12 000 kg/ha).

### Vendanges et pressoir

- Les raisins cueillis vont au pressoir le même mois. Le joueur choisit, cépage par cépage, ce qu'il presse ; le reste est vendu à la Maison Delaunay au prix du contrat ou du marché (6,60 à 8,60 €/kg).
- Un marc de 4 000 kg donne 2 050 L de cuvée + 500 L de taille. Garder la taille : plus de volume, qualité -2. Cuvée seule : qualité +2.
- Sans pressoir : 0,35 €/kg à la coopérative. Au-delà de la cuverie : vinification à façon, 1 €/L.
- Raisins non pressés fin octobre : vendus 15 % sous le prix.

### Cave

- Octobre à décembre : choix de la malolactique (style rond ou vif).
- Janvier à juin : assemblage avec vins clairs de l'année précédente et vins de réserve, puis tirage (1,80 €/bouteille). Fin juin, les vins clairs restants partent en réserve.
- Bonus d'assemblage : trois cépages à 15 % ou plus, +4 ; 10 à 35 % de réserve, +3 ; plus de 50 % de réserve, -2.

| Cuvée | Règle | Vieillissement min. | Prix |
|---|---|---|---|
| Brut sans année | Libre | 15 mois | x 1 |
| Blanc de blancs | 100 % chardonnay | 15 mois | x 1,10 |
| Rosé d'assemblage | Au moins 15 % de pinot noir (vin rouge) | 15 mois | x 1,15 |
| Millésimé | Une seule année exceptionnelle, sans réserve | 36 mois | x 1,35 |

- Dégorgement et dosage : 1,10 €/bouteille. Remuage à la main : 1 jour pour 800 bouteilles ; gyropalettes : 0,15 €/bouteille, aucun jour. Chaque tranche de 6 mois au-delà du minimum : +2 qualité (max +8).
- Sept dosages : brut nature, extra brut, brut, extra dry, sec, demi-sec, doux. Un brut nature de qualité sous 65 perd 4 points.

### Commerce

| Client | Réput. min | Prix/bouteille | Quantité | Exigence | Réputation |
|---|---|---|---|---|---|
| Caviste à Bruxelles | 0 | 19 € | 120–400 | Brut | +2 |
| Pâtissier de Reims | 8 | 21 € | 60–150 | Demi-sec | +1 |
| Organisatrice de mariages | 10 | 21 € | 150–400 | Brut, mars à août | +1 |
| Centrale d'achat de supermarchés | 8 | 13,50 € | 1 500–4 000 | Aucune | -4 |
| Comité d'entreprise | 15 | 19 € | 300–900 | Sept. à déc. | +1 |
| Réseau de cavistes en France | 22 | 18,50 € | 400–1 200 | Brut | +3 |
| Restaurant étoilé à Reims | 28 | 31 € | 60–180 | Extra brut, qualité 64+ | +4 |
| Importateur à Londres | 35 | 20 € | 600–1 500 | Brut | +3 |
| Importateur à Tokyo | 45 | 25 € | 300–900 | Extra brut, qualité 68+ | +4 |
| Palace parisien | 60 | 46 € | 60–200 | Qualité 78+ | +6 |

- Les offres n'arrivent qu'avec une marque déposée (statut RM), 1 à 3 par mois, valables 2 mois. Prix final = prix × (0,75 + qualité / 200) × bonus de cuvée.
- Vente directe : prix public 14 à 60 €. Demande du mois = base × saison × (26 / prix)^1,8 × (0,7 + qualité moyenne / 200). Base = 30 sans marque, sinon 50 + 10 × réputation, +140 avec boutique en ligne, +260 avec caveau.
- Contrat raisins : la Maison Delaunay propose un prix garanti jusqu'en juillet (7,00 à 7,90 €/kg). Elle rachète aussi les bouteilles sur lattes à 11 € × facteur qualité, sans réputation requise.
- Concours : inscription mars ou avril (400 €). En mai : or si qualité 75+ (+8 réputation), argent si 68+ (+4).

## Économie et équilibrage

Serré les deux premières années, puis récompense de la transformation. Équilibrage par simulation automatique, pas à l'intuition.

### Départ

| Élément | Valeur |
|---|---|
| Date | Janvier 2027 |
| Trésorerie | 40 000 € |
| Vignes | 2 ha (0,7 chardonnay, 0,8 pinot noir, 0,5 meunier), santé 85, qualité ≈ 52 |
| Cave | 8 000 places, pas de cuverie, pas de pressoir |
| Stock | 600 bouteilles de brut (coopérative, qualité 55) |
| Vins clairs 2026 du père | 1 200 L pinot noir, 800 L meunier, 1 000 L chardonnay |
| Droits de succession | 75 000 €, 25 000 € chaque 31 décembre pendant 3 ans |
| Réputation | 5 sur 100 |

### Charges et investissements

| Poste | Montant |
|---|---|
| Rémunération du joueur | 2 000 €/mois |
| Chef de culture (+6 jours/mois) | 3 200 €/mois |
| Fermage des Longues Raies | 14 000 €/an |
| Emprunt | 4,5 %/an, 10 % du capital remboursé par an, plafond 120 000 € + 300 000 € par ha possédé |
| Impôts et cotisations | 25 % du résultat annuel positif |
| Marque (statut RM) | 9 000 € |
| Boutique en ligne | 6 000 € |
| Caveau de dégustation | 70 000 € |
| Protection antigel | 18 000 € |
| Pressoir pneumatique | 60 000 € |
| Cuverie +5 000 L | 20 000 € |
| Cave +10 000 bouteilles | 35 000 € |
| Gyropalettes | 25 000 € |
| Clos du Moulin (0,6 ha) | 680 000 € |

### Météo

| Événement | Mois | Probabilité | Effet |
|---|---|---|---|
| Gel de printemps | Avril | 20 % | Récolte -20 à -45 % (moitié avec antigel) |
| Coulure | Juin | 15 % | Récolte -8 à -18 % |
| Belle floraison | Juin | 30 % | Récolte +5 %, bonus millésime +3 |
| Mildiou ou oïdium | Mai–août | 5 % protégé, 45 % sinon | Santé -10 à -20, récolte -5 à -15 % |
| Grêle | Juillet, août | 10 %/mois | Une parcelle perd 15 à 40 % |
| Canicule | Août | 15 % | Récolte -5 % |
| Été idéal | Août | 25 % | Bonus millésime +4 |

Millésime déclaré si le bonus de l'année atteint 6 ou si la qualité moyenne des raisins atteint 72.

### Objectifs d'équilibrage

1. **Passif** (vend tout au négoce, équipes partout) : survit, gagne 10 000 à 20 000 €/an, réputation < 15.
2. **Prudent** (garde 25-35 % des raisins, marque en an 1) : trésorerie jamais sous -20 000 €, dépasse le passif dès l'an 4, réputation 40 en an 6.
3. **Ambitieux** (garde 60 %+, investit beaucoup) : risque réel de faillite en an 2 ou 3, mais meilleur résultat en an 10 s'il tient.
4. **Négligent** (oublie la moitié des travaux) : vigne dégradée, faillite probable avant l'an 5.
5. Première vente sous sa marque vers le mois 16 (cuvée du père tirée en janvier de l'an 1).
6. Une année entière ne peut pas être finie en moins de 30 minutes de jeu réel.

### Problèmes vus dans le prototype

- Trésorerie trop tendue en janvier an 2 : impôts et succession tombent ensemble le 31 décembre. Piste : impôts par trimestre.
- Cave de 8 000 places qui bloque la 2e cuvée. Piste : 12 000 places au départ, ou alerte claire.
- Équipes chères vs jours : le joueur ne sait pas quand déléguer. Piste : afficher le coût d'un jour de travail.
- Temps trop rapide en 2D : garder le rythme mois par mois.

## Contenu éducatif

Le joueur apprend en faisant : chaque action débloque une page du « Carnet du vigneron », chaque mois s'ouvre sur ce qui se passe réellement en Champagne, 12 missions guident la progression. **Tous les textes doivent être relus par Alexis avant publication.**

### Carnet du vigneron

| Page | Ce que le joueur apprend | Débloquée par |
|---|---|---|
| La taille | 4 systèmes autorisés ; la taille fixe rendement et concentration | Première taille |
| La bonne taille | Cordon de Royat pinot noir, Chablis chardonnay, Vallée de la Marne réservée au meunier | Taille idéale |
| Liage, ébourgeonnage, palissage, rognage | À quoi sert chaque geste | Chaque travail |
| Mildiou et oïdium | Chaleur humide contre chaleur sèche | Première protection ou attaque |
| La vendange à la main | Obligatoire : grappes entières pour garder blanc le jus des raisins noirs | Première vendange |
| Le marc de 4 000 kg | 2 050 L de cuvée + 500 L de taille | Premier pressurage |
| Le débourbage | 12 à 24 h de repos du moût | Premier pressurage |
| La malolactique | Acide malique vif, acide lactique doux | Premier choix |
| L'assemblage et les vins de réserve | Cépages, villages, années ; constance du style | Premier assemblage |
| Le rosé d'assemblage | Blanc + rouge, permis en Champagne ; la saignée | Premier rosé |
| Blanc de blancs, blanc de noirs | Raisins blancs seuls, raisins noirs seuls | Premier blanc de blancs |
| Le millésime | Une seule année, 3 ans minimum | Premier millésime |
| Le tirage et la prise de mousse | Liqueur de tirage, seconde fermentation, environ 6 bars | Premier tirage |
| Le vieillissement sur lattes | 15 mois minimum dont 12 sur lies ; arômes de brioche | Premier tirage |
| Le remuage | Pupitres et gyropalettes | Premier dégorgement |
| Le dégorgement | Col dans la saumure glacée, dépôt expulsé | Premier dégorgement |
| Le dosage | Les 7 mentions et leurs grammes de sucre | Premier dégorgement |
| Les lettres de l'étiquette | RM, NM, CM, RC | Création de la marque |
| Vignerons et maisons | Les vignerons possèdent l'essentiel du vignoble, les maisons vendent la majorité des bouteilles | Visite du château |
| Dom Pérignon | N'a pas inventé le champagne ; assemblage et pressurage | Visite de l'église |
| Saint Vincent | Patron des vignerons, fêté vers le 22 janvier | Visite de l'église |
| La craie | Réserve d'eau pour la vigne ; les crayères servent de caves | Agrandissement de la cave |
| Grands et premiers crus | Surface de l'appellation, villages classés | Création de la marque |
| Gel, floraison, ban des vendanges | Risques et calendrier fixé par la filière | Événements météo |
| Prix du raisin, prix et demande, concours | Économie du métier | Contrat, prix public, concours |

### Missions (12)

1. Tailler tes trois parcelles avant fin mars.
2. Visiter l'église du village.
3. Rencontrer la Maison Delaunay au château.
4. Assembler et tirer la cuvée de ton père.
5. Réussir ta première vendange.
6. Presser tes propres raisins.
7. Créer ta marque de champagne.
8. Dégorger et doser ta première cuvée.
9. Vendre 1 000 bouteilles sous ta marque.
10. Atteindre 40 de réputation.
11. Mettre un millésime en cave.
12. Décrocher une médaille d'or.

Chaque mission rapporte 2 points de réputation et une page de carnet.

### Autres formes d'apprentissage

- **Texte du mois** : 2-3 phrases sur ce qui se passe en Champagne ce mois-là, au résumé de fin de mois.
- **Quiz de la loge de vigne** : 3 questions tirées des pages débloquées ; bonne série = +1 réputation.
- **Dégustation à l'assemblage** : chaque vin clair a une description (fruité, vif, rond, minéral).

## Feuille de route (9 étapes, chacune validée sur téléphone)

0. Mise en place · 1. Monde et contrôles · 2. Simulation et équilibrage (cœur du projet) · 3. Vignes et saisons · 4. Pressoir et cave · 5. Commerce, banque, château · 6. Contenu éducatif · 7. Graphismes et son · 8. Mode Défi du bar.

## Points à vérifier avant de vendre le jeu

- [ ] Le mot « Champagne » dans le nom d'un produit : appellation très protégée (Comité Champagne). Avis juridique ou nom sans le mot.
- [ ] Alcool : âge minimum conseillé (PEGI) et règles de publicité (loi Évin) si vendu en France.
- [ ] Exactitude des faits : relecture complète du carnet par Alexis (34 000 ha, 17 grands crus et 42 premiers crus, part du vignoble des vignerons, règles de taille par cépage).
- [ ] Licences des modèles 3D et sons : chaque fichier listé dans `docs/CREDITS.md`.
- [ ] Abonnement Claude : accès à Claude Code et au réseau pour installer les paquets.
