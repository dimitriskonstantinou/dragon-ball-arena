import type { User } from '../types/game';

/** The logged-in account, or null (the server answers 401 when nobody is logged in). */
export async function currentUser(): Promise<User | null> {
  const response = await fetch('/api/me', { credentials: 'same-origin' });
  return response.ok ? ((await response.json()) as User) : null;
}
