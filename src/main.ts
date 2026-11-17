import { Scene } from 'three';

// Page d'accueil provisoire : vérifie que Three.js et la publication fonctionnent.
const scene = new Scene();
const statut = document.getElementById('statut');
if (statut) statut.textContent = `Le jeu arrive bientôt (moteur 3D prêt : ${scene.type}).`;
