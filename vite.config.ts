import { defineConfig } from 'vitest/config';

// base './' : le jeu fonctionne sous n'importe quelle adresse GitHub Pages.
export default defineConfig({ base: './', test: { include: ['tests/**/*.test.ts'] } });
