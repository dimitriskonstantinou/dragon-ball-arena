// The one place that knows the game connection's event names and payloads (CLAUDE.md "Socket.IO API").
import { io, type Socket } from 'socket.io-client';
import type { Character, GameView, Role } from '../types/game';

export interface ServerToClient {
  'character-list': (characters: Character[]) => void;
  'auth-required': () => void;
  'match-status': (text: string) => void;
  'game-start': (start: { roomId: string; role: Role }) => void;
  'update-state': (state: GameView) => void;
  message: (text: string) => void;
  'error-msg': (text: string) => void;
}

export interface ClientToServer {
  'find-match': (characterIds: [string, string, string]) => void;
  'queue-skill': (move: { charId: string; skillId: string; targetPlayerKey: Role; targetIndex: number }) => void;
  'cancel-skill': (move: { charId: string }) => void;
  'commit-turn': (payment: { paymentList: string[] }) => void;
  surrender: () => void;
}

export type GameSocket = Socket<ServerToClient, ClientToServer>;

/** Survives a reload, differs per tab: the server puts this page straight back into its match (Step 41). */
export function pageId(): string {
  const fresh = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('');
  try {
    const stored = sessionStorage.getItem('pageId');
    if (stored) return stored;
    sessionStorage.setItem('pageId', fresh);
  } catch {
    // storage blocked: reconnecting still works, a reload waits for the server instead
  }
  return fresh;
}

/** Same origin as the page (the login cookie only works there); connects only when asked to. */
export function createSocket(): GameSocket {
  const socket: GameSocket = io({ autoConnect: false, auth: { page: pageId() } });
  // Say goodbye when the page closes, so the opponent isn't kept waiting (Step 41).
  window.addEventListener('pagehide', () => {
    if (socket.connected) socket.disconnect();
  });
  return socket;
}
