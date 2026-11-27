// What the server sends. Mirrors backend/game_engine.view_for + strip_skill_internals and app.characters_for_user;
// fields the server strips (socket/account ids, effects, base_*, cast_seq, ko_seq, rng_*) never appear here.

export type KiType = 'energy' | 'martial' | 'spirit' | 'rage';
export type CostKind = KiType | 'random';
export type Role = 'p1' | 'p2';
export type TargetType = 'enemy' | 'enemy_team' | 'self' | 'ally' | 'ally_team';

export interface Skill {
  id: string;
  name: string;
  description: string;
  cost: Partial<Record<CostKind, number>>;
  cooldown: number;
  currentCooldown: number;
  target_type: TargetType;
  classes?: string[];
  image?: string;                   // site-relative, versioned: /photos/skills/x.webp?v=...
  locked?: boolean;
  locked_reason?: string;
  ignores_invulnerable?: true;      // sent only when true
}

export interface Status {
  type: string;                     // stun, silence, dot, hot, protected, ... (see frontend STATUS_META)
  duration: number;                 // in ticks: 1 turn = 2 ticks
  value?: number;
  tag?: 'harmful' | 'buff';
  classes?: string[];
}

export interface Character {
  id: string;
  name: string;
  image: string;
  health: number;
  maxHealth: number;
  defense: number;
  status: Status[];
  skills: Skill[];
}

export interface PlayerView {
  username: string;
  resources: KiType[];
  status: Status[];
  team: Character[];
  connected: boolean;
  timeouts?: number;
}

export interface QueuedMove {
  charId: string;
  skillId: string;
  targetPlayerKey: Role;
  targetIndex: number;
}

export interface GameView {
  roomId: string;
  turn: Role | null;
  turn_count: number;
  winner: Role | null;              // never a draw (Step 29)
  started_at: string;
  pending_moves: QueuedMove[];      // empty unless it's your turn
  players: Record<Role, PlayerView>;
  turn_seconds_left: number | null;
}

export interface UserStats {
  total_wins: number;
  total_losses: number;
  total_matches: number;
  current_win_streak: number;
  current_loss_streak: number;
  longest_win_streak: number;
  win_rate: number;
}

export interface User {
  id: number;
  username: string;
  email: string;
  stats: UserStats;
}
