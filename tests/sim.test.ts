import { describe, it, expect } from 'vitest';
import { VERSION_SIM } from '../src/sim';

describe('simulation', () => {
  it('se charge sans affichage', () => {
    expect(VERSION_SIM).toBe(0);
  });
});
