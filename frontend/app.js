// Accounts require a real session cookie, which only works reliably
// same-origin -- so the socket connects to wherever this page was served
// from, and doesn't connect at all until we know the user is logged in.
const socket = io({ autoConnect: false });
let myRole = null;
let myRoomId = null;
let selectedCharId = null;
let selectedSkillId = null;
let selectedSkillObj = null;
let currentGameState = null;
let currentUser = null;

const KI_LABELS = {
    energy: 'Energy Ki', martial: 'Martial Ki', spirit: 'Spirit Ki',
    rage: 'Rage Ki', random: 'Any Ki type',
};

// Lobby Data
let selectedChars = [];

// Payment Logic
let payment_auto = [];
let payment_random_needed = 0;
let payment_random_selected = [];
let payment_available_pool = [];

// --- AUTH ---
function showAuthScreen() {
    document.getElementById('auth-screen').style.display = 'block';
    document.getElementById('topbar').style.display = 'none';
    document.getElementById('lobby-screen').style.display = 'none';
    document.getElementById('game-screen').style.display = 'none';
}

function showLogin() {
    document.getElementById('login-form').style.display = 'block';
    document.getElementById('register-form').style.display = 'none';
}

function showRegister() {
    document.getElementById('login-form').style.display = 'none';
    document.getElementById('register-form').style.display = 'block';
}

async function postJson(url, body) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, data };
}

async function doLogin() {
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const errEl = document.getElementById('login-error');
    errEl.innerText = '';
    const { ok, data } = await postJson('/api/login', { username, password });
    if (!ok) { errEl.innerText = data.error || 'Login failed'; return; }
    onAuthenticated(data);
}

async function doRegister() {
    const username = document.getElementById('register-username').value.trim();
    const email = document.getElementById('register-email').value.trim();
    const password = document.getElementById('register-password').value;
    const errEl = document.getElementById('register-error');
    errEl.innerText = '';
    const { ok, data } = await postJson('/api/register', { username, email, password });
    if (!ok) { errEl.innerText = data.error || 'Registration failed'; return; }
    onAuthenticated(data);
}

async function doLogout() {
    await fetch('/api/logout', { method: 'POST' });
    currentUser = null;
    if (socket.connected) socket.disconnect();
    location.reload();
}

function onAuthenticated(user) {
    currentUser = user;
    document.getElementById('auth-screen').style.display = 'none';
    document.getElementById('topbar').style.display = 'flex';
    document.getElementById('lobby-screen').style.display = 'block';
    renderUserBadge(user);
    if (!socket.connected) socket.connect();
}

function renderUserBadge(user) {
    const s = user.stats || {};
    document.getElementById('user-badge-text').innerText =
        `${user.username}  |  W:${s.total_wins || 0} L:${s.total_losses || 0}  |  Streak:${s.current_win_streak || 0}`;
}

async function refreshUserBadge() {
    const res = await fetch('/api/me');
    if (res.ok) renderUserBadge(await res.json());
}

async function checkExistingSession() {
    const res = await fetch('/api/me');
    if (res.ok) onAuthenticated(await res.json());
    else showAuthScreen();
}

document.addEventListener('DOMContentLoaded', checkExistingSession);

socket.on('auth-required', () => showAuthScreen());

// --- LOBBY LOGIC ---
socket.on('character-list', (list) => {
    const grid = document.getElementById('char-grid');
    grid.innerHTML = '';
    list.forEach(char => {
        const card = document.createElement('div');
        card.className = 'select-card';
        card.id = `char-select-${char.id}`;
        card.onclick = () => toggleCharSelect(char.id);
        card.innerHTML = `<img src="${char.image}"><h3>${char.name}</h3>`;
        grid.appendChild(card);
    });
});

function toggleCharSelect(id) {
    const index = selectedChars.indexOf(id);
    if(index > -1) {
        selectedChars.splice(index, 1);
        document.getElementById(`char-select-${id}`).classList.remove('selected');
    } else {
        if(selectedChars.length < 3) {
            selectedChars.push(id);
            document.getElementById(`char-select-${id}`).classList.add('selected');
        }
    }
    document.getElementById('find-match-btn').disabled = (selectedChars.length !== 3);
}

function findMatch() {
    document.getElementById('find-match-btn').disabled = true;
    socket.emit('find-match', selectedChars);
}

socket.on('match-status', (msg) => { document.getElementById('lobby-status').innerText = msg; });

socket.on('game-start', (data) => {
    myRoomId = data.roomId;
    myRole = data.role;
    document.getElementById('lobby-screen').style.display = 'none';
    document.getElementById('game-screen').style.display = 'block';
    updateTitle();
});

socket.on('opponent-left', () => {
    log('⚠ Opponent disconnected.');
});

// --- GAME LOGIC ---

socket.on('message', msg => { log(msg); });

socket.on('update-state', game => {
    currentGameState = game;
    resetTargeting();
    closeModal();

    if(game.winner) {
        document.getElementById('status').innerText = game.winner === myRole ? "YOU WIN!" : "YOU LOSE!";
        document.getElementById('end-turn').style.display = 'none';
        refreshUserBadge();
        return;
    }

    const isMyTurn = game.turn === myRole;
    document.getElementById('status').innerText = isMyTurn ? "PLAN YOUR MOVES" : "OPPONENT THINKING...";
    document.getElementById('end-turn').style.display = isMyTurn ? 'inline-block' : 'none';

    const myData = game.players[myRole];
    const enemyRole = myRole === 'p1' ? 'p2' : 'p1';
    const enemyData = game.players[enemyRole];

    // UPDATE TURN INDICATOR
    updateTurnHeader(isMyTurn, myData.team[0].image, enemyData.team[0].image);

    const remainingDice = calculateRemainingDice(myData.resources, game.pending_moves);
    document.getElementById('my-ki-count').innerText = remainingDice.length;

    renderMyDice(myData.resources, game.pending_moves);
    renderDice('enemy-dice', enemyData.resources, false);
    renderTeam('my-team', myData.team, true, isMyTurn, game.pending_moves, remainingDice);
    renderTeam('enemy-team', enemyData.team, false, false, [], []);
    renderPlayerStatus('my-player-status', myData.status);
    renderPlayerStatus('enemy-player-status', enemyData.status);
});

function renderPlayerStatus(elementId, statusList) {
    const el = document.getElementById(elementId);
    if (!el) return;
    if (!statusList || statusList.length === 0) { el.innerHTML = ''; return; }
    el.innerHTML = statusList.map(s => {
        const meta = describeStatus(s);
        return `<span class="status-badge ${meta.cls}" style="display:inline-block; margin: 2px;">${meta.icon} ${meta.label} <span style="font-weight:normal">(${formatTurns(s.duration)})</span></span>`;
    }).join('');
}

function updateTurnHeader(isMyTurn, myImg, enemyImg) {
    const myBox = document.getElementById('my-avatar-box');
    const enemyBox = document.getElementById('enemy-avatar-box');

    document.getElementById('my-avatar-img').src = myImg;
    document.getElementById('enemy-avatar-img').src = enemyImg;

    if (isMyTurn) {
        myBox.classList.add('my-turn-active');
        enemyBox.classList.remove('enemy-turn-active');
    } else {
        myBox.classList.remove('my-turn-active');
        enemyBox.classList.add('enemy-turn-active');
    }
}

socket.on('error-msg', msg => log("❌ " + msg));

// --- MATH ---
function calculateRemainingDice(totalDice, pendingMoves) {
    let pool = [...totalDice];
    if (!pendingMoves) return pool;
    pendingMoves.forEach(move => {
        const cost = move.cost;
        for (const [type, amt] of Object.entries(cost)) {
            if (type === 'random') continue;
            for (let i=0; i<amt; i++) {
                let idx = pool.indexOf(type);
                if(idx > -1) pool.splice(idx, 1);
            }
        }
        if (cost.random) {
            for (let i=0; i<cost.random; i++) {
                if (pool.length > 0) pool.shift();
            }
        }
    });
    return pool;
}

function canAfford(pool, cost) {
    let tempPool = [...pool];
    for (const [type, amt] of Object.entries(cost)) {
        if (type === 'random') continue;
        let foundCount = 0;
        tempPool = tempPool.filter(die => {
            if (die === type && foundCount < amt) {
                foundCount++;
                return false;
            }
            return true;
        });
        if (foundCount < amt) return false;
    }
    if (cost.random) {
        if (tempPool.length < cost.random) return false;
    }
    return true;
}

// --- RENDERING ---
function renderDice(elementId, dice, clickable = false) {
    const container = document.getElementById(elementId);
    container.innerHTML = '';
    dice.sort().forEach((type, idx) => {
        const d = document.createElement('div');
        d.className = `die ${type}`;
        d.title = KI_LABELS[type] || type;
        if(clickable) { d.onclick = () => onPaymentDieClick(idx, type); }
        container.appendChild(d);
    });
}

function renderMyDice(dicePool, pendingMoves) {
    const container = document.getElementById('my-dice');
    container.innerHTML = '';
    let pool = [...dicePool].sort();
    let usedFlags = new Array(pool.length).fill(false);

    if (pendingMoves) {
        pendingMoves.forEach(move => {
            Object.entries(move.cost).forEach(([type, amt]) => {
                if(type === 'random') return;
                for(let i=0; i<amt; i++) {
                    for(let j=0; j<pool.length; j++) {
                        if(pool[j] === type && !usedFlags[j]) {
                            usedFlags[j] = true;
                            break;
                        }
                    }
                }
            });
        });
    }

    pool.forEach((type, index) => {
        const d = document.createElement('div');
        d.className = `die ${type} ${usedFlags[index] ? 'locked' : ''}`;
        d.title = usedFlags[index] ? `${KI_LABELS[type] || type} (reserved for a queued move)` : (KI_LABELS[type] || type);
        container.appendChild(d);
    });
}

// 1 tick left = "ends after this turn"; ticks come in pairs (1 round = 2 ticks).
function formatTurns(duration) {
    if (duration === 1) return "Ends after this turn";
    return `${Math.ceil(duration / 2)} Turn(s)`;
}

const STATUS_META = {
    stun:                  { icon: '⚡', label: 'STUNNED',         cls: 'status-stun' },
    silence:               { icon: '🔇', label: 'SILENCED',        cls: 'status-debuff' },
    dot:                   { icon: '☠️', label: 'BLEEDING',        cls: 'status-debuff' },
    hot:                   { icon: '💚', label: 'REGEN',           cls: 'status-buff' },
    heal_block:            { icon: '🚫', label: 'HEAL BLOCKED',    cls: 'status-debuff' },
    invulnerable:          { icon: '🛡️', label: 'INVULNERABLE',   cls: 'status-buff' },
    physical_invulnerable: { icon: '🛡️', label: 'PHYS. IMMUNE',   cls: 'status-buff' },
    chakra_invulnerable:   { icon: '🛡️', label: 'KI IMMUNE',      cls: 'status-buff' },
    mental_invulnerable:   { icon: '🛡️', label: 'MENTAL IMMUNE',  cls: 'status-buff' },
    dodge:                 { icon: '💨', label: 'DODGE READY',     cls: 'status-buff' },
    counter:               { icon: '🔁', label: 'COUNTER READY',   cls: 'status-buff' },
    reflect:               { icon: '🪞', label: 'REFLECT READY',   cls: 'status-buff' },
    chakra_restrict:       { icon: '🔒', label: 'KI LOCKED',       cls: 'status-debuff' },
    chakra_drain_over_time:{ icon: '🌀', label: 'KI DRAIN',        cls: 'status-debuff' },
    protected:             { icon: '🙏', label: 'PROTECTED',       cls: 'status-buff' },
    delayed_damage:        { icon: '💥', label: 'CHARGING HIT',    cls: 'status-debuff' },
};

const PERCENT_MODS = {
    damage_taken_mod:  { icon: '🎯', suffix: 'DMG TAKEN',    buffWhenNegative: true },
    damage_dealt_mod:  { icon: '⚔️', suffix: 'DMG DEALT',    buffWhenNegative: false },
    heal_received_mod: { icon: '💉', suffix: 'HEALING RECV', buffWhenNegative: false },
    heal_dealt_mod:    { icon: '💉', suffix: 'HEALING DEALT', buffWhenNegative: false },
};

function describeStatus(s) {
    const mod = PERCENT_MODS[s.type];
    if (mod) {
        const isBuff = mod.buffWhenNegative ? s.value < 0 : s.value >= 0;
        const pct = Math.round(s.value * 100);
        return { icon: mod.icon, label: `${pct >= 0 ? '+' : ''}${pct}% ${mod.suffix}`, cls: isBuff ? 'status-buff' : 'status-debuff' };
    }
    return STATUS_META[s.type] || { icon: '❔', label: s.type.toUpperCase(), cls: 'status-debuff' };
}

function isSilencedFor(char, skill) {
    if (!char.status) return false;
    const skillClasses = skill.classes || [];
    return char.status.some(s => {
        if (s.type !== 'silence') return false;
        if (!s.classes || s.classes.length === 0) return true;
        return s.classes.some(c => skillClasses.includes(c));
    });
}

function renderTeam(elementId, team, isMine, isMyTurn, pendingMoves, remainingDice) {
    const container = document.getElementById(elementId);
    container.innerHTML = '';

    team.forEach((char, index) => {
        const card = document.createElement('div');
        card.className = 'char-card' + (char.health <= 0 ? ' dead' : '');

        if (!isMine) {
            card.onclick = () => onEnemyClicked(index);
        } else {
            card.onclick = () => onAllyClicked(index);
        }

        const hpPct = (char.health / char.maxHealth) * 100;
        let controlsHtml = '';

        // --- STATUS EFFECT CHECK ---
        let isStunned = false;
        let statusHtml = '';
        if(char.status && char.status.length > 0) {
            statusHtml = '<div class="status-container">';
            char.status.forEach(s => {
                if(s.type === 'stun') isStunned = true;
                if(s.invisible) return; // e.g. a hidden counter-trap the target isn't meant to see coming
                const meta = describeStatus(s);
                const text = formatTurns(s.duration);
                statusHtml += `<div class="status-badge ${meta.cls}">${meta.icon} ${meta.label}<br><span style="font-weight:normal; font-size:9px;">${text}</span></div>`;
            });
            statusHtml += '</div>';
        }

        const shieldHtml = (char.defense && char.defense > 0)
            ? `<div class="shield-badge">🛡️ SHIELD ${char.defense}</div>`
            : '';

        if (isMine) {
            const queuedMove = pendingMoves && pendingMoves.find(m => m.charId === char.id);
            if (queuedMove) {
                controlsHtml = `<button class="cancel-btn" onclick="event.stopPropagation(); cancelMove('${char.id}')">CANCEL ${queuedMove.skillName}</button>`;
            } else {
                char.skills.forEach(skill => {
                    let costHtml = '';
                    Object.entries(skill.cost).forEach(([type, amt]) => {
                        for(let i=0; i<amt; i++) costHtml += `<span class="cost-box ${type}" title="${KI_LABELS[type] || type}"></span>`;
                    });

                    const affordable = canAfford(remainingDice, skill.cost);
                    const silenced = isSilencedFor(char, skill);
                    const disabled = !isMyTurn || char.health <= 0 || isStunned || silenced || skill.locked || skill.currentCooldown > 0 || !affordable ? 'disabled' : '';
                    let disabledReason = '';
                    if (char.health <= 0) disabledReason = 'This character has been defeated.';
                    else if (isStunned) disabledReason = 'Stunned -- cannot act this turn.';
                    else if (silenced) disabledReason = 'Silenced -- this skill is blocked.';
                    else if (skill.locked) disabledReason = skill.locked_reason || 'This skill is locked.';
                    else if (skill.currentCooldown > 0) disabledReason = `On cooldown: ${skill.currentCooldown} more turn(s).`;
                    else if (!affordable) disabledReason = 'Not enough Ki of the right type(s) left this turn.';
                    const cdText = skill.currentCooldown > 0 ? `(${skill.currentCooldown})` : '';
                    const iconHtml = skill.image
                        ? `<img src="${skill.image}" class="skill-icon" onerror="this.style.display='none'">`
                        : '';

                    controlsHtml += `
                        <button class="skill-btn" ${disabled} onclick="onSkillClicked('${char.id}', '${skill.id}', this, event)" title="${disabledReason}">
                            ${iconHtml}
                            <div style="flex-grow:1">
                                <b>${skill.name}</b> ${skill.locked ? '🔒' : ''} ${cdText}
                                <div style="font-size:0.8em; color:#aaa">${skill.description}</div>
                            </div>
                            <div style="min-width:30px">${costHtml}</div>
                        </button>
                    `;
                });
            }
        }
        card.innerHTML = `
            ${statusHtml}
            <img src="${char.image}" class="char-img">
            ${shieldHtml}
            <div class="hp-bar"><div class="hp-fill" style="width:${hpPct}%"></div><span class="hp-text">${char.health}/${char.maxHealth}</span></div>
            <div style="padding:5px; font-weight:bold;">${char.name}</div>
            ${controlsHtml}
        `;
        container.appendChild(card);
    });
}

// --- INTERACTION ---

// Skill ids only need to be unique *within one character's own kit* --
// several characters intentionally share an id (e.g. "afterimage_technique"
// for the universal defensive skill). So selecting a skill must always be
// scoped to the specific character whose button was clicked, never looked
// up by skill id alone across the whole team.
function onSkillClicked(charId, skillId, btnElement, event) {
    if (event) event.stopPropagation(); // don't let this click also bubble up and fire onAllyClicked on the parent card

    document.querySelectorAll('.skill-btn').forEach(b => b.classList.remove('selected'));
    btnElement.classList.add('selected');

    selectedCharId = charId;
    selectedSkillId = skillId;
    selectedSkillObj = null;

    const myTeam = currentGameState.players[myRole].team;
    const ownerChar = myTeam.find(c => c.id === charId);
    if (ownerChar) {
        selectedSkillObj = ownerChar.skills.find(s => s.id === skillId) || null;
    }

    if (!selectedSkillObj) return;

    const type = selectedSkillObj.target_type || 'enemy';

    document.getElementById('enemy-team').classList.remove('targeting-mode');
    document.getElementById('my-team').classList.remove('targeting-mode');

    if (type === 'enemy' || type === 'enemy_team') {
        updateInstruction(type === 'enemy_team' ? "SELECT ANY ENEMY (hits the whole team)" : "SELECT AN ENEMY");
        document.getElementById('enemy-team').classList.add('targeting-mode');
    } else if (type === 'ally' || type === 'ally_team') {
        updateInstruction(type === 'ally_team' ? "SELECT ANY ALLY (affects the whole team)" : "SELECT AN ALLY");
        document.getElementById('my-team').classList.add('targeting-mode');
    } else if (type === 'self') {
        updateInstruction("CLICK SELF");
        document.getElementById('my-team').classList.add('targeting-mode');
    }
}

function onEnemyClicked(targetIndex) {
    if (!selectedSkillId || !selectedSkillObj) return;
    const type = selectedSkillObj.target_type || 'enemy';
    if (type !== 'enemy' && type !== 'enemy_team') return;

    const enemyRole = myRole === 'p1' ? 'p2' : 'p1';
    socket.emit('queue-skill', {
        roomId: myRoomId,
        charId: selectedCharId,
        skillId: selectedSkillId,
        myPlayerKey: myRole,
        targetPlayerKey: enemyRole,
        targetIndex: targetIndex
    });
    resetTargeting();
}

function onAllyClicked(targetIndex) {
    if (!selectedSkillId || !selectedSkillObj) return;
    const type = selectedSkillObj.target_type;
    if (type !== 'ally' && type !== 'ally_team' && type !== 'self') return;

    socket.emit('queue-skill', {
        roomId: myRoomId,
        charId: selectedCharId,
        skillId: selectedSkillId,
        myPlayerKey: myRole,
        targetPlayerKey: myRole,
        targetIndex: targetIndex
    });
    resetTargeting();
}

function resetTargeting() {
    selectedCharId = null;
    selectedSkillId = null;
    selectedSkillObj = null;
    document.querySelectorAll('.skill-btn').forEach(b => b.classList.remove('selected'));
    document.getElementById('enemy-team').classList.remove('targeting-mode');
    document.getElementById('my-team').classList.remove('targeting-mode');
    updateInstruction("");
}

function cancelMove(charId) {
    socket.emit('cancel-skill', { roomId: myRoomId, myPlayerKey: myRole, charId: charId });
}

// --- PAYMENT MODAL ---
function openPaymentModal() {
    const moves = currentGameState.pending_moves || [];
    if(moves.length === 0) {
        socket.emit('commit-turn', { roomId: myRoomId, paymentList: [] });
        return;
    }
    const modal = document.getElementById('payment-modal');
    const myResources = [...currentGameState.players[myRole].resources];

    let specificCosts = [];
    payment_random_needed = 0;

    moves.forEach(m => {
        Object.entries(m.cost).forEach(([type, amt]) => {
            if(type === 'random') payment_random_needed += amt;
            else {
                for(let i=0; i<amt; i++) specificCosts.push(type);
            }
        });
    });

    payment_auto = [];
    let tempPool = [...myResources];
    let possible = true;

    specificCosts.forEach(req => {
        const idx = tempPool.indexOf(req);
        if(idx > -1) {
            payment_auto.push(req);
            tempPool.splice(idx, 1);
        } else {
            possible = false;
        }
    });

    if(!possible) { alert("Error: Cost mismatch. Please refresh."); return; }

    payment_available_pool = tempPool;
    payment_random_selected = [];
    renderPaymentUI();
    modal.showModal();
}

function renderPaymentUI() {
    const autoContainer = document.getElementById('auto-paid-container');
    autoContainer.innerHTML = '';
    payment_auto.forEach(type => {
        const d = document.createElement('div');
        d.className = `die ${type} locked`;
        autoContainer.appendChild(d);
    });

    const randomContainer = document.getElementById('random-slots-container');
    randomContainer.innerHTML = '';
    for(let i=0; i<payment_random_needed; i++) {
        const slot = document.createElement('div');
        slot.className = 'random-slot';
        if(i < payment_random_selected.length) {
            const type = payment_random_selected[i];
            slot.className = `die ${type}`;
            slot.onclick = () => removeRandomSelection(i);
        } else {
            slot.innerText = '?';
        }
        randomContainer.appendChild(slot);
    }

    const availContainer = document.getElementById('available-payment-dice');
    availContainer.innerHTML = '';
    payment_available_pool.forEach((type, idx) => {
        const d = document.createElement('div');
        d.className = `die ${type}`;
        d.onclick = () => selectRandomDie(idx);
        availContainer.appendChild(d);
    });

    const btn = document.getElementById('confirm-payment-btn');
    btn.disabled = payment_random_selected.length !== payment_random_needed;
}

function selectRandomDie(poolIndex) {
    if(payment_random_selected.length >= payment_random_needed) return;
    const die = payment_available_pool[poolIndex];
    payment_available_pool.splice(poolIndex, 1);
    payment_random_selected.push(die);
    renderPaymentUI();
}

function removeRandomSelection(slotIndex) {
    const die = payment_random_selected[slotIndex];
    payment_random_selected.splice(slotIndex, 1);
    payment_available_pool.push(die);
    renderPaymentUI();
}

function submitPayment() {
    const finalPayment = [...payment_auto, ...payment_random_selected];
    socket.emit('commit-turn', { roomId: myRoomId, paymentList: finalPayment });
    closeModal();
}

function closeModal() { document.getElementById('payment-modal').close(); }
function updateInstruction(text) { document.getElementById('instruction').innerText = text; }
function updateTitle() { if(myRole) document.title = myRole === 'p1' ? "Earth (P1)" : "Saiyan (P2)"; }
function log(msg) { const l = document.getElementById('log'); l.innerHTML += `<div>> ${msg}</div>`; l.scrollTop = l.scrollHeight; }
