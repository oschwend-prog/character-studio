// Sign-in helpers. An iPhone Home Screen app keeps its storage apart from Safari, so a magic link
// (PKCE: the code verifier lives where the link was requested) opened from Mail lands in Safari and
// cannot finish the exchange. In the installed app the emailed 6-digit code is the primary route.

interface Env {
  matchMedia?: (query: string) => { matches: boolean };
  navigator?: { standalone?: boolean };
}

/** True inside the installed (Home Screen) app. */
export function isStandalone(env: Env = typeof window === 'undefined' ? {} : (window as unknown as Env)): boolean {
  if (env.matchMedia?.('(display-mode: standalone)').matches) return true;
  return env.navigator?.standalone === true;
}

/** The emailed one-time code with spaces or dashes removed; null unless it is 6 to 10 digits. */
export function normaliseOtpCode(input: string): string | null {
  const digits = input.replace(/[\s-]/g, '');
  return /^\d{6,10}$/.test(digits) ? digits : null;
}
