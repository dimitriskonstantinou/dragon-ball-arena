import { useEffect, useState } from 'react';
import { currentUser } from './net/api';
import { createSocket } from './net/socket';
import type { User } from './types/game';

type Connection = 'checking' | 'logged-out' | 'connecting' | 'connected' | 'disconnected';

/** Step 46: the foundation only. Proves login detection and the typed game connection; the screens follow in 47-48. */
export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [connection, setConnection] = useState<Connection>('checking');
  const [characters, setCharacters] = useState(0);

  useEffect(() => {
    let socket: ReturnType<typeof createSocket> | null = null;
    let cancelled = false;
    currentUser().then((me) => {
      if (cancelled) return;
      if (!me) {
        setConnection('logged-out');
        return;
      }
      setUser(me);
      setConnection('connecting');
      socket = createSocket();
      socket.on('connect', () => setConnection('connected'));
      socket.on('disconnect', () => setConnection('disconnected'));
      socket.on('character-list', (list) => setCharacters(list.length));
      socket.on('auth-required', () => setConnection('logged-out'));
      socket.connect();
    });
    return () => {
      cancelled = true;
      socket?.disconnect();
    };
  }, []);

  return (
    <main style={{ maxWidth: 640, margin: '64px auto', padding: 'var(--space-3)' }}>
      <h1 style={{ color: 'var(--gold)' }}>Dragon Ball Arena</h1>
      <p>
        The new interface is being built. To play, use the <a href="/">current one</a>.
      </p>
      <p data-testid="connection" aria-live="polite">
        {connection === 'checking' && 'Checking your login...'}
        {connection === 'logged-out' && (
          <>
            Not logged in. <a href="/">Log in on the current page</a>, then come back.
          </>
        )}
        {connection === 'connecting' && `Logged in as ${user?.username}. Connecting...`}
        {connection === 'connected' && `Logged in as ${user?.username}. Connected: ${characters} characters available.`}
        {connection === 'disconnected' && 'Connection lost. It reconnects by itself.'}
      </p>
    </main>
  );
}
