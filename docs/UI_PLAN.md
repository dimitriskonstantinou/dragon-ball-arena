# Dragon Ball Arena — UI / Frontend Plan

Companion to [PLAN.md](PLAN.md). Frontend today: one `index.html`, one 644-line `app.js`,
one 129-line `style.css`, vanilla JS, no build step. **Keep it vanilla.** At this size a framework
adds more weight than it removes. Split the code into ES modules instead.

---

## 1. What makes it unfriendly today (from the code)

### Battle screen
1. **You can't see what the opponent did.** HP numbers just change. The log (`#log`) is a 100px green
   terminal that mostly shows errors. The server sends no "X used Y on Z" events.
2. **Too much text in too little space.** Every skill is a full-width button with its whole description inside
   a 220px card: 12 text buttons for your team. The board doesn't fit a laptop screen, and you scroll between
   your team and the enemy's.
3. **Targeting is unclear.** Click skill → small gold text above the board → click a card. The red "pulse" on
   targetable cards never runs (`@keyframes pulse` is undefined). Self skills still make you click yourself;
   team skills make you click "any enemy". Invalid targets (dead) aren't separated from valid ones.
4. **Paying is a chore.** Any random cost opens a modal where you hand-pick dice, every turn.
5. **Disabled reasons are hover-only** (`title` attribute): slow, invisible on touch, easy to miss.
6. **Ki is color-only**, and red/green are two of the four types, which is a colorblind problem. Dice have no
   symbol or letter.
7. **No feedback on hits.** HP bar is always red regardless of HP; no damage numbers, no flash on the struck card.
8. **Status badges cover the portrait** (absolute top-right, stacked) and say "Ends after this turn" /
   "N Turn(s)" in tiny text.
9. **Turn header** shows only your first character's picture; no usernames, no timer.
10. **Game over is a dead end.** Text changes to "YOU WIN!"; no return to lobby; Find Match stays disabled;
    you have to reload.
11. Errors go to the bottom of the log where nobody looks.

### Lobby & auth
12. You can't see a character's skills before picking them.
13. Grid is fixed at 5 columns with 80px-tall crops; no visible "your team (2/3)" slots; no cancel while searching.
14. "How to play" is wrong ("both players' queued moves resolve"; turns actually alternate).
15. Login/register aren't `<form>`s, so **Enter doesn't submit**; no loading state on the buttons.

### Cross-cutting
16. Not responsive (fixed widths), no mobile layout.
17. Accessibility: click targets are `div`s, no keyboard support, no visible focus, no `aria-live` for game events.
18. HTML is built with `innerHTML` strings and inline `onclick="...'${id}'..."`, which is fragile and becomes XSS
    the moment any text is user-provided.
19. Leftover tab title "Earth (P1)" / "Saiyan (P2)".
20. Each match downloads ~1.8 MB of skill icons rendered at 32px (see PLAN §5, image assets).

---

## 2. Target design

### Battle layout (desktop: fits 1366×768 with no scrolling)

```
┌────────────────────────────────────────────────────────────────────────┐
│ DRAGON BALL ARENA   you (12W 4L)   ⏱ 0:42 ███████░░  YOUR TURN  [Surrender] │
├──────────────────────────────┬─────────────────────────────────────────┤
│ YOUR TEAM                    │                              ENEMY TEAM │
│ [portrait] Goku  ▇▇▇▇▇▇░ 80  │  70 ░▇▇▇▇▇▇ Raditz  [portrait]           │
│  [K][Kk][KA🔒][AI]  ⚡STUN 1  │      🛡 15  ●(status chips)              │
│ [portrait] Piccolo ...       │  ...                                    │
│ [portrait] Tien ...          │  ...                                    │
├──────────────────────────────┴─────────────────────────────────────────┤
│ SKILL DETAIL: Kamehameha · 25 dmg · cost [E][?] · CD 0 · classes: —     │
│               ✖ Not enough Energy Ki (shown inline, not hover-only)     │
├────────────────────────────────────────────────────────────────────────┤
│ KI  E×2  M×1  S×0  R×1   (reserved: E×1)        [ END TURN ⏎ ]          │
│ BATTLE LOG  ▸ Raditz used Knee Attack on Goku: 25 dmg, Stunned (1 turn) │
└────────────────────────────────────────────────────────────────────────┘
```

- **Skills as 48px icons** in a row under each portrait (Naruto-Arena-style). Name, description, cost,
  cooldown and *why it's unavailable* go in one shared detail panel (on hover, or tap on touch).
- Cooldown number overlaid on the icon; 🔒 overlay for locked; dimmed + ✖ for unaffordable.
- Enemy side mirrors yours, without skill icons (or with them read-only, a design choice).
- **Status chips** sit in a row under the HP bar, not over the art. Tap/hover for details. Short form "1T".
- HP bar color ramps green → yellow → red. Defense shows as a blue segment/badge next to it.

### Interaction
- Click a skill → **only valid targets** light up (alive, correct side); everything else dims.
- `self` skills queue immediately with no target click. `*_team` skills: one click anywhere on that side,
  and the whole side highlights.
- Queued move shows as a small icon badge on the actor (click it to cancel). `Esc` / right-click cancels
  the current selection.
- **Auto-pay**: random costs are assigned automatically (spend the type you have the most of that no queued
  skill needs). "Adjust payment" opens the existing modal for people who want control. No modal when there
  are no random costs.
- Keyboard: `1–4` pick a skill of the focused character, `Tab` cycles characters, `Enter` ends turn, `Esc` cancels.

### Feedback
- Server battle events (PLAN §6) feed a readable log + **floating damage/heal numbers** + a short flash on the struck card.
- "YOUR TURN" banner on turn change; timer bar turns red under 10s.
- Errors appear as a toast near the action, not at the bottom of the log.
- End screen: result, W/L and streak change, **[Play again]** (same team) and **[Back to lobby]**.

### Lobby
- Character cards with portrait + name; click to open a skill list (icons, descriptions, costs).
- Three team slots at the top ("Your team 2/3"); click a card to add, click a slot to remove.
- Remember the last team (localStorage, wrapped in try/catch).
- Find Match ↔ **Cancel search**; show "searching… 0:12".
- Fix the "How to play" text; short Ki legend with symbols.

### Visual language
- Dragon Ball palette: deep navy background, orange/gold accents (`--gold`, `--orange`), blue for energy.
- **Ki dice get a symbol + color**: Energy ⚡ blue, Martial ✊ green, Spirit ✦ white, Rage 🔥 red,
  Random ? gray. That works for colorblind players and in grayscale.
- Colors as CSS custom properties on `:root`; one spacing/size scale; `prefers-reduced-motion` turns off
  pulses and floating numbers.

### Responsive
- ≥1100px: two columns as above.
- 700–1100px: same, smaller portraits (64px), skill icons 40px.
- <700px: enemy team on top as a compact row, your team below, detail panel as a bottom sheet, END TURN sticky.

---

## 3. Code structure

```
frontend/
  index.html
  css/  base.css  lobby.css  battle.css
  js/
    main.js        boot, screen switching
    net.js         socket + fetch wrappers (one place for every event name)
    state.js       current game view, selection, derived values (remainingKi, canAfford, validTargets)
    dom.js         tiny el('div', {class, onclick}, children) helper, so no innerHTML for data
    auth.js
    lobby.js
    battle.js      board rendering
    payment.js     auto-pay + adjust modal
    log.js         battle log + toasts + floating numbers
```

- `<script type="module">` (no bundler). Flask already serves `frontend/`.
- Event delegation on containers instead of inline `onclick` strings.
- Render from one `state` object (`render(state)`) instead of ad-hoc DOM edits.
- `canAfford` / `remainingKi` must use the **same algorithm as the server** (specific costs first, then random),
  so the UI never greys out a skill the server would accept, or the reverse.

---

## 4. Phases

Each phase: measure before/after (`tools/measure.py` + the manual UI metrics below), screenshots in the PR.

| Phase | Scope | Depends on |
|---|---|---|
| **UI-1 Quick wins** | `<form>` for auth (Enter submits), fix How-to-play text, define/replace the pulse, game-over → Back to lobby / Play again, toasts for errors, remove dead code, fix tab title, HP color ramp, Ki symbols | nothing |
| **UI-2 Structure** | Split into modules, `dom.js` helper, event delegation, no `innerHTML` with data | UI-1 |
| **UI-3 Battle layout** | Icon skills + detail panel, status chips, valid-target highlighting, auto-target self, auto-pay, keyboard shortcuts | UI-2, PLAN Phase 1 (per-player view, server cost validation) |
| **UI-4 Feedback** | Battle log from server events, floating numbers, turn banner, timer bar, surrender button | PLAN §6 battle events, Phase 2 timer/surrender |
| **UI-5 Lobby & polish** | Skill preview, team slots, remember team, cancel search, responsive breakpoints, a11y pass, reduced-motion | UI-2 |

---

## 5. How we measure UI progress

| Metric | Baseline (today) | Target | How |
|---|---|---|---|
| Clicks for a typical turn (3 moves, each with 1 random cost) | **11** (3×skill+target, End, 3 dice, Confirm) | **≤ 6** | Count it manually |
| Board fits 1366×768 without scrolling | No | Yes | Browser window at that size |
| Skill-icon bytes per match | ~1.8 MB | < 150 KB | `tools/measure.py` assets section / DevTools Network |
| Frontend JS+CSS+HTML | 37.7 KB | < 60 KB uncompressed | `tools/measure.py` |
| Disabled reason visible without hover | No | Yes | Manual |
| Opponent's actions visible | No | Every action logged | Manual: play a turn |
| Keyboard-only full turn | Impossible | Possible | Manual |
| Lighthouse accessibility | not measured | ≥ 90 | Chrome DevTools → Lighthouse (record before UI-1) |
