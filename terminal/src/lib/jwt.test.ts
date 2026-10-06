import { describe, expect, it } from 'vitest';
import { isJwtExpired } from './supabase';

describe('an expired sign-in is recognised', () => {
  it('by PostgREST code or message, and nothing else', () => {
    expect(isJwtExpired({ code: 'PGRST301', message: 'x' })).toBe(true);
    expect(isJwtExpired({ code: 'PGRST303', message: 'x' })).toBe(true);
    expect(isJwtExpired({ message: 'JWT expired' })).toBe(true);
    expect(isJwtExpired({ code: 'PGRST205', message: 'could not find the table' })).toBe(false);
    expect(isJwtExpired(null)).toBe(false);
  });
});
