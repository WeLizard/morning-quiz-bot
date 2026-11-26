/* «Ночной город»: client kit and the room app (window.NightCity). Design: approved preview v2 on the noir_print_a art.
   kit  — rule-agnostic components (scene strip by location and time of day, role card back → face, seats with portraits,
          two-step picker, evidence and dossier frames, case log, chat with kept drafts, server-time timer, dock, alerts).
          The weekly case mode reuses them; nothing in the kit knows the short mafia rules.
   app  — the shared entry (company, invitation, your rooms, open tables, Telegram group), rooms, invites and links, and the
          short mafia test game as a thin layer over the kit (MQB-004; it is a platform check, not the future game).
   DOM is built with createElement only: names, messages and server text are never parsed as HTML. */
(() => {
'use strict';
const ART = '/app/night/';
const SHELL_ART = ART + 'shell/';           // neutral shell: shell.json, skyline.svg, icons.svg, the title font
const WORLD_ART = ART + 'worlds/';          // index.json + <world>/pack.json and its art
const DEFAULT_WORLD = 'manor_lake';         // the world of the test mafia
const SVG_NS = 'http://www.w3.org/2000/svg';
const STUB = {nav: {setRoot() {}}, menu: {register() {}}, header: {mountGear() {}, mountBack() {}}};
const shell = () => window.QW || STUB;
// Polls and clock ticks never keep a non-browser host alive (unit tests run in Node).
const later = (callback, delay) => { const handle = setTimeout(callback, delay); handle?.unref?.(); return handle; };

/* ================= DOM helpers ================= */
function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = String(text);
    return node;
}
const textNode = value => (document.createTextNode ? document.createTextNode(String(value)) : el('span', null, value));
function put(node, ...children) {
    for (const child of children.flat(Infinity)) {
        if (child == null || child === false || child === '') continue;
        node.append(typeof child === 'string' || typeof child === 'number' ? textNode(child) : child);
    }
    return node;
}
function attr(node, map) {
    for (const [key, value] of Object.entries(map)) if (value != null && value !== false) node.setAttribute(key, value === true ? '' : String(value));
    return node;
}
const withClass = (node, name) => { node.classList.add(name); return node; };
const setVar = (node, name, value) => { try { node.style?.setProperty?.(name, value); } catch { /* CSSOM only */ } };
/* rich text: ['Ночью мафия вывела ', {b: 'Олега'}, {cls: 'nc-role-mafia', text: 'мафия'}] */
function rich(parts, tag = 'span', cls) {
    const node = el(tag, cls);
    for (const part of [].concat(parts ?? [])) {
        if (part == null || part === '') continue;
        if (typeof part === 'string' || typeof part === 'number') node.append(textNode(part));
        else if (part.b != null) node.append(el('b', part.cls, part.b));
        else if (part.text != null) node.append(el('span', part.cls, part.text));
        else node.append(part);
    }
    return node;
}

/* ================= kit ================= */
const kit = {};

/* --- shell and world packs (scripts/art/night_city/README.md) ---
   The shell is neutral and has no world: ink, ivory, one red stamp; the vector scene skyline.svg, one vector icon sprite.
   A world pack (/app/night/worlds/<id>/pack.json) brings what makes a story its own: scenes by SLOT and time of day,
   the 17 table portraits, faction emblems, card backs, frames and a palette (+ the contrast values).
   Screens never name a place: they ask for a slot (cover, title, lobby, night, day, vote, finale, out) and a time.
   A missing slot borrows a neighbour (vote → day → lobby, out → night → lobby, finale → cover → title); nothing left, or the pack
   failed to load → the shell's vector scene. The pack is loaded lazily when a room opens, never for the shell screens. */
const TIMES = ['morning', 'day', 'evening', 'night'];
const SLOTS = ['cover', 'title', 'lobby', 'night', 'day', 'vote', 'finale', 'out'];
const SLOT_CHAIN = {vote: ['day', 'lobby'], out: ['night', 'lobby'], finale: ['cover', 'title']};
const WORLD_ID = /^[a-z][a-z0-9_]{1,31}$/;
const ICON_ALIAS = {hands: 'plane'};
/* A pack that is missing or failed: the faction emblem is drawn from the shell sprite instead. */
const EMBLEM_ICON = {emblem_shadow: 'eye', emblem_investigation: 'seal', emblem_independent: 'laurel'};
/* pack.json palette key → CSS custom property on <html> (night-city.css maps them onto --qw-game-*) */
const PALETTE_VARS = {page: '--nc-page', page_rgb: '--nc-page-rgb', surface: '--nc-surface', surface_2: '--nc-surface-2', line: '--nc-line',
    edge: '--nc-edge', accent_soft: '--nc-edge-soft', rule: '--nc-rule', text: '--nc-text', muted: '--nc-muted', accent: '--nc-accent',
    accent_hi: '--nc-accent-hi', accent_lo: '--nc-accent-lo', accent_ink: '--nc-accent-ink', accent_text: '--nc-accent-text',
    tint: '--nc-tint', btn: '--nc-btn', btn_text: '--nc-btn-text', field: '--nc-field', field_line: '--nc-field-line', plate: '--nc-plate',
    shadow: '--nc-shadow', investigation: '--nc-invest', independent: '--nc-indep'};
const CONTRAST_VARS = {line: '--nc-line-hc', edge: '--nc-edge-hc', muted: '--nc-muted-hc', accent_text: '--nc-accent-text-hc',
    shadow: '--nc-shadow-hc', investigation: '--nc-invest-hc'};
const skin = {pack: null, v: ''};          // the pack applied to the screens (null = the shell)
const packCache = new Map();               // world id → {promise, failedAt}: a failed load is retried after 30 s
let indexPromise = null, indexData = null;

async function fetchJson(url, ms = 8000) {
    if (typeof fetch !== 'function') throw new Error('no fetch');
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), ms) : null;
    try {
        const response = await fetch(url, {credentials: 'same-origin', ...(controller ? {signal: controller.signal} : {})});
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return await response.json();
    } finally { if (timer) clearTimeout(timer); }
}
/** The promise's value, or undefined after `ms` (the promise keeps running). The timer never outlives the promise. */
const within = (promise, ms) => new Promise(resolve => {
    const timer = setTimeout(() => resolve(undefined), ms); timer?.unref?.();
    promise.then(value => { clearTimeout(timer); resolve(value); }, () => { clearTimeout(timer); resolve(undefined); });
});
const safeColor = value => (typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value) ? value : null);

/** worlds/index.json: [{id, title, era, thumb, accent, version, default}] — null when it cannot be loaded (nothing breaks, chips and the picker hide). */
kit.worldIndex = () => {
    if (indexPromise) return indexPromise;
    const promise = fetchJson(WORLD_ART + 'index.json').then(data => {
        const worlds = (Array.isArray(data?.worlds) ? data.worlds : []).filter(item => item && WORLD_ID.test(String(item.id)) && typeof item.title === 'string')
            .map(item => ({id: item.id, title: item.title, era: typeof item.era === 'string' ? item.era : '', accent: safeColor(item.accent),
                version: typeof item.version === 'string' && /^[0-9a-f]{4,64}$/.test(item.version) ? item.version : '',
                thumb: typeof item.thumb === 'string' && /^[a-z0-9_]+\/[a-z0-9_]+\.webp$/.test(item.thumb) ? item.thumb : null, default: item.default === true,
                age: asAge(item.age)}));
        return worlds.length ? {default: WORLD_ID.test(String(data.default)) ? data.default : DEFAULT_WORLD, worlds} : null;
    }).catch(() => null).then(index => { if (index) indexData = index; else if (indexPromise === promise) indexPromise = null; return index; });
    indexPromise = promise;
    return promise;
};
/** A world of the loaded index (null until it is loaded or when it cannot be). */
kit.worldEntry = id => indexData?.worlds.find(item => item.id === id) || null;
kit.thumbUrl = entry => (entry?.thumb ? `${WORLD_ART}${entry.thumb}${entry.version ? '?v=' + entry.version : ''}` : '');

const validPack = (data, id) => Boolean(data && typeof data === 'object' && data.schema === 'nc-world-pack/1' && data.id === id
    && data.palette && typeof data.palette === 'object' && data.scenes && typeof data.scenes === 'object'
    && Array.isArray(data.portraits) && data.factions && typeof data.factions === 'object' && data.backs && data.frames);
/** Loads (once) the pack of a world → pack | null (never rejects; null = the shell stays). Needs no screen. */
kit.loadPack = id => {
    if (!WORLD_ID.test(String(id))) return Promise.resolve(null);
    const hit = packCache.get(id);
    if (hit && (!hit.failedAt || Date.now() - hit.failedAt < 30000)) return hit.promise;
    const entry = {failedAt: 0, promise: null};
    entry.promise = (async () => {
        const index = await kit.worldIndex();
        const version = index?.worlds.find(item => item.id === id)?.version || '';
        const data = await fetchJson(`${WORLD_ART}${id}/pack.json${version ? '?v=' + version : ''}`);
        if (!validPack(data, id)) throw new Error('not a world pack');
        return Object.assign(data, {v: version || (typeof data.version === 'string' && /^[0-9a-f]{4,64}$/.test(data.version) ? data.version : '')});
    })().catch(() => { entry.failedAt = Date.now(); return null; });
    packCache.set(id, entry);
    return entry.promise;
};
/** Applies the pack to the screens: palette tokens on <html>, art by slot. null → the neutral shell. */
kit.useWorld = pack => {
    skin.pack = pack || null; skin.v = pack?.v || '';
    const root = document.documentElement;
    const style = root?.style;
    if (style?.removeProperty) for (const name of [...Object.values(PALETTE_VARS), ...Object.values(CONTRAST_VARS), '--nc-display']) style.removeProperty(name);
    if (pack && style?.setProperty) {
        for (const [key, name] of Object.entries(PALETTE_VARS)) if (typeof pack.palette[key] === 'string') style.setProperty(name, pack.palette[key]);
        for (const [key, name] of Object.entries(CONTRAST_VARS)) if (typeof pack.palette.contrast?.[key] === 'string') style.setProperty(name, pack.palette.contrast[key]);
        if (typeof pack.font?.display === 'string' && pack.font.display) style.setProperty('--nc-display', pack.font.display);
    }
    if (root?.dataset) { if (pack) root.dataset.ncWorld = pack.id; else delete root.dataset.ncWorld; }
};
Object.defineProperty(kit, 'world', {get: () => skin.pack?.id ?? null});
Object.defineProperty(kit, 'pack', {get: () => skin.pack});
const packUrl = file => (skin.pack && typeof file === 'string' && /^[a-z0-9_]+\.webp$/.test(file)
    ? `${WORLD_ART}${skin.pack.id}/${file}${skin.v ? '?v=' + skin.v : ''}` : '');

/* --- scenes: slot × time of day --- */
/** Pack file for a slot and time: the exact time, else the nearest time of the slot, else the neighbour slots; null → the shell's scene. */
function sceneHit(slot, time) {
    const scenes = skin.pack?.scenes;
    if (!scenes || !SLOTS.includes(slot)) return null;
    for (const name of [slot, ...(SLOT_CHAIN[slot] || [])]) {
        const entry = scenes[name];
        if (!entry || typeof entry !== 'object') continue;
        const times = entry.times && typeof entry.times === 'object' ? entry.times : {};
        let file = entry.file;
        // No time asked (a borrowed slot): the slot's own default time.
        const want = TIMES.includes(time) && !(SLOT_CHAIN[slot] && name !== slot) ? time : (TIMES.includes(entry.default) ? entry.default : time);
        if (!file && times[want]) file = times[want];
        if (!file) {
            const at = Math.max(0, TIMES.indexOf(want));
            const nearest = Object.keys(times).filter(key => TIMES.includes(key)).sort((a, b) => Math.abs(TIMES.indexOf(a) - at) - Math.abs(TIMES.indexOf(b) - at))[0];
            file = nearest ? times[nearest] : null;
        }
        const url = packUrl(file);
        if (url) return {url, focus: typeof entry.focus === 'string' && /^[\d.]+%? [\d.]+%?$/.test(entry.focus) ? entry.focus : null};
    }
    return null;
}
/* --- backgrounds of the shell: swappable by slot like a world's (shell/shell.json), the vector skyline.svg as the fallback.
   entry (sign-in), rooms (backdrop of the lists), invite, empty (no tables), loading. A missing file or slot → skyline.svg.
   nc-shell/2: a slot is {portrait, landscape} (720 / 1280 px, drawn for the UI: calm dark top ~15% and bottom ~40%);
   nc-shell/1: a slot is one file for every shape. The orientation follows the box the picture fills (scene strip, empty-state
   picture) or the viewport (page backdrop), and changes when the phone turns. --- */
const SHELL_SLOTS = ['entry', 'rooms', 'invite', 'empty', 'loading'];
const SHELL_FALLBACK = SHELL_ART + 'skyline.svg';
const SHELL_FILE = /^[a-z0-9_]+\.(svg|webp)$/;
const ORIENTS = ['portrait', 'landscape'];
let shellScenes = null, shellPromise = null, lastPage = null;
let shellMusic = null;                    // shell themes of shell.json (file names), null until it is loaded
const shellLate = [];                     // repaints waiting for shell.json
kit.loadShell = () => {
    if (shellPromise) return shellPromise;
    const promise = fetchJson(SHELL_ART + 'shell.json').then(data => {
        const scenes = {};
        for (const slot of SHELL_SLOTS) {
            const value = data?.scenes?.[slot];
            const files = {};
            if (typeof value === 'string') { if (SHELL_FILE.test(value)) files.portrait = files.landscape = value; }
            else if (value && typeof value === 'object') for (const orient of ORIENTS) if (typeof value[orient] === 'string' && SHELL_FILE.test(value[orient])) files[orient] = value[orient];
            if (files.portrait || files.landscape) scenes[slot] = {portrait: files.portrait || files.landscape, landscape: files.landscape || files.portrait};
        }
        shellScenes = scenes;
        shellMusic = (Array.isArray(data?.music) ? data.music : []).map(item => item?.file).filter(file => typeof file === 'string' && MUSIC_SHELL_FILE.test(file));
        // screens drawn before shell.json arrived showed skyline.svg: give them their pictures now
        for (const repaint of shellLate.splice(0)) repaint();
        if (lastPage) kit.pageScene(lastPage);
        return scenes;
    }).catch(() => { if (shellPromise === promise) shellPromise = null; return null; });
    shellPromise = promise;
    return promise;
};
/** Orientation of a box {width, height} (default: the viewport); unknown → portrait (the phone first). */
const orientOf = (width = globalThis.innerWidth, height = globalThis.innerHeight) =>
    (Number(width) > 0 && Number(height) > 0 && width / height >= 1 ? 'landscape' : 'portrait');
/** URL of a shell background slot in an orientation (default: the viewport's); skyline.svg when shell.json is not loaded,
    has no such slot or names an odd file. */
kit.shellUrl = (slot, orient = orientOf()) => {
    const files = shellScenes?.[slot];
    const file = files?.[ORIENTS.includes(orient) ? orient : 'portrait'];
    return file ? SHELL_ART + file : SHELL_FALLBACK;
};
/** {slot, time, shell} → URL of the scene picture: the world's, else the shell background `shell` (default entry). */
kit.sceneUrl = ({slot, time, shell = 'entry'} = {}) => sceneHit(slot, time)?.url || kit.shellUrl(shell);
/* One observer for every box that shows a shell background: the picture follows the box's shape (rotation, a wider column). */
const shellBoxes = new WeakMap();
let shellObserver = null;
function fitShell(node, slot, apply, guess = null) {
    let last = [];
    const pick = (width, height, force = false) => {
        last = [width, height];
        const orient = orientOf(width, height);
        if (node.dataset) { if (node.dataset.orient === orient && !force) return; node.dataset.orient = orient; }
        apply(kit.shellUrl(slot, orient));
    };
    if (!shellScenes) shellLate.push(() => pick(...last, true));
    if (guess) pick(guess === 'landscape' ? 2 : 1, 1); else pick();   // first paint: a known shape or the viewport's; the observer corrects it
    if (typeof ResizeObserver !== 'function') return;
    shellObserver ||= new ResizeObserver(entries => {
        for (const entry of entries) shellBoxes.get(entry.target)?.(entry.contentRect.width, entry.contentRect.height);
    });
    shellBoxes.set(node, pick);
    shellObserver.observe(node);
}
/** A picture of a shell slot for an empty state: falls back to skyline.svg when the file does not load. */
kit.shellPicture = slot => {
    const img = el('img', 'nc-empty-pic');
    img.alt = ''; img.dataset.shell = slot;
    img.addEventListener('error', () => { if (img.src && !img.src.endsWith(SHELL_FALLBACK)) img.src = SHELL_FALLBACK; });
    fitShell(img, slot, url => { img.src = url; }, 'landscape');   // a wide strip in a list row
    return img;
};
kit.art = name => {
    const pack = skin.pack, value = String(name);
    if (!pack) return '';
    if (value === 'card_back_role') return packUrl(pack.backs?.role);
    const frame = /^frame_(hero|evidence|dossier)$/.exec(value);
    if (frame) return packUrl(pack.frames?.[frame[1]]?.file);
    const emblem = /^emblem_(shadow|investigation|independent)$/.exec(value);
    if (emblem) return packUrl(pack.factions?.[emblem[1]]?.emblem);
    return '';
};
/** Frame geometry of the pack as CSS custom properties: aspect (--fa) and the window's insets (--fl, --ft, --fr, --fb). */
function frameVars(node, name) {
    const frame = skin.pack?.frames?.[name];
    const [l, t, r, b] = Array.isArray(frame?.hole) ? frame.hole : [];
    if (![l, t, r, b].every(Number.isFinite) || !Array.isArray(frame.aspect)) return false;
    setVar(node, '--fa', `${frame.aspect[0]} / ${frame.aspect[1]}`);
    setVar(node, '--fl', `${l * 100}%`); setVar(node, '--ft', `${t * 100}%`); setVar(node, '--fr', `${(1 - r) * 100}%`); setVar(node, '--fb', `${(1 - b) * 100}%`);
    return true;
}

/** Icon from the shell's vector sprite (one for all worlds, currentColor); 'emblem_*' is the world's faction emblem (pack art; the sprite without a pack). */
kit.icon = (name, {size, alt = ''} = {}) => {
    let key = String(name);
    let node;
    const emblem = key.startsWith('emblem_') ? kit.art(key) : '';
    if (emblem) {
        node = el('img', 'ic emb-art'); node.src = emblem; node.alt = alt;
    } else {
        if (key.startsWith('emblem_')) key = EMBLEM_ICON[key] || 'seal';
        node = el('span', 'ic');
        const make = tag => (document.createElementNS ? document.createElementNS(SVG_NS, tag) : document.createElement(tag));
        const svg = make('svg'), use = make('use');
        svg.setAttribute('viewBox', '0 0 24 24'); use.setAttribute('href', `${SHELL_ART}icons.svg#nc-i-${ICON_ALIAS[key] || key}`);
        svg.append(use); node.append(svg);
    }
    if (alt) node.setAttribute('aria-label', alt); else node.setAttribute('aria-hidden', 'true');
    if (size) setVar(node, '--s', size + 'px');
    return node;
};

/** Age mark of a world: 12 (no badge), 16 or 18. The server's `world_age` of a room or table, else the index entry's `age`, else the known darker worlds. A mark only. */
const KNOWN_AGE = {deep_choir: 16, dead_air: 16, velvet_circle: 18, eternal_hotel: 18};
const AGES = [12, 16, 18];
const asAge = value => (AGES.includes(Number(value)) ? Number(value) : 12);
kit.worldAge = (id, age = null) => Math.max(asAge(age), asAge(kit.worldEntry(id)?.age), asAge(KNOWN_AGE[id]));
const ageBadge = age => Object.assign(el('b', `nc-age a${age}`, `${age}+`), {title: `Для игроков от ${age} лет`});
/** «Story» chip of a room or table: the cover thumbnail of the world and its name (needs the loaded index; null otherwise); «16+» for the darker worlds. */
kit.worldChip = (entry, age = null) => {
    if (!entry) return null;
    const chip = el('span', 'nc-world-chip');
    const url = kit.thumbUrl(entry);
    if (url) { const img = el('img'); img.src = url; img.alt = ''; chip.append(img); }
    chip.append(el('span', null, entry.title));
    if (kit.worldAge(entry.id, age) >= 16) chip.append(ageBadge(kit.worldAge(entry.id, age)));
    if (entry.accent) setVar(chip, '--w-accent', entry.accent);
    return chip;
};

/** Scene strip with the copy on its own scrim. slot: cover|title|lobby|night|day|vote|finale|out (omitted → the shell's scene);
    size: 'tall' (entry, finale) | 'short' (action screens) | ''. */
kit.scene = ({slot = null, time, shell = 'entry', eyebrow, title, text, body = [], steps = null, bar = null, size = ''} = {}) => {
    const hit = sceneHit(slot, time);
    const node = el('section', `nc-hero nc-span ${size}${hit ? '' : ' nc-shell-scene'}`.trim());
    node.dataset.slot = slot || 'shell';
    setVar(node, '--img-fb', `url(${SHELL_FALLBACK})`);
    if (hit) { setVar(node, '--img', `url(${hit.url})`); setVar(node, '--pos', hit.focus || '50% 40%'); }
    else { node.dataset.shell = shell; fitShell(node, shell, url => setVar(node, '--img', `url(${url})`)); }
    const copy = el('div', 'copy');
    put(copy, eyebrow ? (typeof eyebrow === 'object' ? eyebrow : el('span', 'nc-eyebrow', eyebrow)) : null, rich(title, 'h2'), text ? rich(text, 'p') : null, body, steps, bar);
    node.append(copy);
    return node;
};
/** Backdrop of the page on wide screens (night-city.css picks --page-img-l when the viewport is landscape). */
kit.pageScene = (spec = {}) => {
    lastPage = spec;
    const root = document.documentElement || {style: null};
    const world = sceneHit(spec.slot, spec.time)?.url;
    setVar(root, '--page-img', `url(${world || kit.shellUrl(spec.shell || 'entry', 'portrait')})`);
    setVar(root, '--page-img-l', `url(${world || kit.shellUrl(spec.shell || 'entry', 'landscape')})`);
};
/** Phase steps: [{id, label, icon}], current id. */
kit.steps = (list, current) => {
    const node = attr(el('div', 'nc-steps'), {'aria-label': 'Фаза'});
    for (const step of list) {
        const item = put(el('span', step.id === current ? 'on' : ''), step.icon ? kit.icon(step.icon) : null, step.label);
        if (step.id === current) attr(item, {'aria-current': 'step'});
        node.append(item);
    }
    return node;
};

/* --- timer: counts down to a server deadline (epoch seconds) using the server clock offset --- */
// A window of the weekly case runs for hours: «13 ч 52 м». Short phases keep minutes and seconds.
const clockText = seconds => seconds >= 3600 ? `${Math.floor(seconds / 3600)} ч ${Math.floor(seconds % 3600 / 60)} м`
    : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
kit.clockText = clockText;
/** {endsAt, serverNow, total, icon, alive(), onExpire} → {clock, bar, remaining(), stop()} */
kit.timer = ({endsAt, serverNow, total = 0, icon = 'hourglass', alive = () => true, onExpire = null} = {}) => {
    const offset = Number.isFinite(serverNow) ? serverNow - Date.now() / 1000 : 0;
    const remaining = () => Math.max(0, Math.ceil(endsAt - (Date.now() / 1000 + offset)));
    const label = el('span', 'nc-clock-text');
    const clock = put(attr(el('span', 'nc-clock'), {role: 'timer'}), kit.icon(icon), label);
    const fill = el('i'), bar = put(attr(el('div', 'nc-time'), {role: 'progressbar', 'aria-label': 'Осталось времени'}), fill);
    let stopped = false, fired = false;
    const tick = () => {
        if (stopped || !alive()) return;
        const left = remaining();
        label.textContent = clockText(left);
        attr(clock, {'aria-label': `До конца фазы ${clockText(left)}`});
        const share = total > 0 ? Math.min(100, Math.round(left / total * 100)) : 0;
        fill.style.width = share + '%'; attr(bar, {'aria-valuenow': share});
        if (left <= 0 && !fired) { fired = true; onExpire?.(); return; }
        later(tick, 1000);
    };
    tick();
    return {clock, bar, remaining, stop() { stopped = true; }};
};

/* --- people --- */
/** Table portraits of the world's pack (role-neutral heroes, 17); the number is the room's portrait number and survives a change of world. */
Object.defineProperty(kit, 'PORTRAITS', {get: () => skin.pack?.portraits?.length || 17});
kit.portraitUrl = portrait => {
    const list = skin.pack?.portraits;
    if (!Array.isArray(list) || !list.length) return '';
    const number = typeof portrait === 'string' && /^seat_\d\d$/.test(portrait) ? Number(portrait.slice(5)) : Number(portrait) || 1;
    const item = list.find(entry => entry.n === number) || list[((number - 1) % list.length + list.length) % list.length];
    return packUrl(item?.file);
};
/** Portrait in the ring of the world's edge colour: portrait = 1…kit.PORTRAITS or 'seat_07'. No pack → a neutral silhouette. */
kit.avatar = ({portrait = 1, size = '', me = false, out = false} = {}) => {
    const node = attr(el('span', ['nc-ava', size, me ? 'me' : ''].filter(Boolean).join(' ')), {'aria-hidden': 'true'});
    const url = kit.portraitUrl(portrait);
    if (url) setVar(node, '--p', `url(${url})`);
    else node.append(withClass(kit.icon('people'), 'ph'));
    if (out) { node.append(withClass(kit.icon('ghost'), 'gh')); }
    return node;
};
/** [{name, sub, portrait, me, out, end: [nodes]}] */
kit.seats = items => {
    const list = el('ul', 'nc-seats');
    for (const item of items) {
        const li = el('li', `nc-seat${item.out ? ' out' : ''}`);
        const who = put(el('div'), el('span', 'nm', item.name), item.sub ? rich(item.sub, 'span', 'sub') : null);
        put(li, kit.avatar({portrait: item.portrait, me: item.me, out: item.out}), who, put(el('div', 'end'), item.end || []));
        list.append(li);
    }
    return list;
};
kit.tag = (text, {tone = '', icon = null} = {}) => put(el('span', `nc-tag ${tone}`.trim()), icon ? kit.icon(icon) : null, text);
/** Seat track: total places, taken, ready (ready ⊂ taken). */
kit.track = ({total = 12, taken = 0, ready = 0, label = null} = {}) => {
    const node = attr(el('div', 'nc-track'), label ? {'aria-label': label, role: 'img'} : {'aria-hidden': 'true'});
    for (let i = 0; i < total; i++) node.append(el('i', i < ready ? 'ready' : i < taken ? 'in' : ''));
    return node;
};

/* --- panels and controls --- */
kit.head = (icon, title, count = '') => put(el('div', 'nc-head'), icon ? kit.icon(icon) : null, el('h2', 'nc-h3', title), count ? el('span', 'nc-count', count) : null);
kit.panel = ({icon = null, title = '', count = '', cls = ''} = {}, ...children) =>
    put(el('section', `nc-card ${cls}`.trim()), title ? kit.head(icon, title, count) : null, children);
kit.note = (text, cls = 'nc-note') => rich(text, 'p', cls);
/** Core .qw-btn: kind primary | secondary | text | danger; compact for list rows. */
kit.button = (label, onClick, {kind = 'secondary', icon = null, disabled = false, compact = false, crumb = null} = {}) => {
    const node = put(el('button', `qw-btn ${kind}${compact ? ' compact' : ''}`), icon ? kit.icon(icon) : null, label);
    node.type = 'button'; node.disabled = Boolean(disabled);
    if (crumb) node.dataset.qwCrumb = crumb;
    node.addEventListener('click', event => { if (!node.disabled) onClick?.(event); });
    return node;
};
kit.stack = (...buttons) => put(el('div', 'qw-btn-stack'), buttons);
kit.row = (...buttons) => put(el('div', 'qw-btn-row'), buttons);
kit.alert = ({tone = 'warn', icon = 'alert', title, text = '', actions = []} = {}) => {
    const body = put(el('div'), rich(title, 'strong'), text ? rich(text, 'p') : null, actions.length ? kit.row(...actions) : null);
    return put(attr(el('div', `nc-alert ${tone}`), {role: 'status'}), kit.icon(icon), body);
};
kit.closed = (icon, text) => put(el('div', 'nc-closed'), kit.icon(icon), rich(text));
kit.secret = text => put(el('p', 'nc-secret'), kit.icon('lock'), text);
/** Bottom dock: hint over one button group; layout 'stack' | 'row' (primary last in a row). */
kit.dock = ({hint = '', buttons = [], layout = 'stack'} = {}) =>
    put(el('div', 'nc-dock'), put(el('div'), hint ? rich(hint, 'p', 'nc-dock-hint') : null, layout === 'row' ? kit.row(...buttons) : kit.stack(...buttons)));
kit.netBanner = ({text = 'Нет связи · повторяем сами', onRetry} = {}) =>
    put(attr(el('div', 'nc-net'), {role: 'status'}), kit.icon('alert'), el('span', null, text), onRetry ? kit.button('Повторить', onRetry, {compact: true}) : null);
/** Text field + action in one row (invitation code or link). */
kit.joinField = ({onSubmit, placeholder = 'Код или ссылка', label = 'Код или ссылка приглашения', value = ''} = {}) => {
    const input = attr(el('input', 'nc-field'), {placeholder, 'aria-label': label, autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', maxlength: 400});
    input.type = 'text'; input.value = value;
    const go = kit.button('Войти', () => onSubmit?.(input.value, go, input));
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault?.(); go.click(); } });
    return put(el('div', 'nc-join'), input, go);
};
/** Sealed ticket with the invitation code and a copy button. */
kit.ticket = ({code, onCopy} = {}) => {
    const copy = attr(el('button', 'qw-icon-btn nc-copy'), {'aria-label': 'Скопировать код', title: 'Скопировать код'});
    copy.type = 'button'; copy.append(kit.icon('papers')); copy.addEventListener('click', () => onCopy?.(code));
    const value = attr(el('span', 'nc-code-value', code), {'aria-label': 'Код приглашения'});
    return put(el('div', `nc-code${String(code).length > 12 ? ' long' : ''}`), kit.icon('key'), value, copy);
};
kit.toggle = ({title, text = '', on = false, onChange} = {}) => {
    const knob = el('span', 'qw-switch'); knob.dataset.on = String(on);
    const control = attr(el('button'), {role: 'switch', 'aria-checked': String(on), 'aria-label': title}); control.type = 'button';
    control.append(knob); control.addEventListener('click', () => onChange?.(!on));
    return put(el('div', 'nc-toggle'), put(el('div'), el('strong', null, title), text ? el('span', null, text) : null), control);
};

/* --- role: collapsed badge, card back → face --- */
const FACTIONS = {shadow: {emblem: 'emblem_shadow', name: 'Знак Тени', cls: 'nc-role-mafia'},
                  investigation: {emblem: 'emblem_investigation', name: 'Знак Следствия', cls: 'nc-role-town'}};
/** {title, line, icon, faction, action: {label, onClick}} — «Ты — детектив · Показать». */
kit.roleBadge = ({title, line = '', icon = 'emblem_investigation', faction = 'investigation', action = null} = {}) => {
    const emb = kit.icon(icon); emb.classList.add('emb');
    return put(el('div', 'nc-mine'), emb, put(el('div'), el('strong', FACTIONS[faction]?.cls, title), line ? rich(line) : null),
        action ? kit.button(action.label, action.onClick, {kind: 'text', compact: true}) : el('span'));
};
/** face=false: the back (card_back_role); face=true: frame_hero + faction emblem + title + side. */
/** A horizontal swipe on a card: pointer events, ≥ 40 px and wider than tall (vertical movement stays page scroll, touch-action: pan-y).
    handler(direction): +1 to the right, -1 to the left. A swipe is no click: the tap path guards itself with `used`. */
const SWIPE_MIN = 40;
kit.flip = {dir: 1};      // direction of the last flip: the card face turns up from that side
function swipeable(node, handler) {
    let start = null;
    node.addEventListener('pointerdown', event => { start = {x: event.clientX, y: event.clientY}; });
    node.addEventListener('pointercancel', () => { start = null; });
    node.addEventListener('pointerup', event => {
        if (!start) return;
        const dx = event.clientX - start.x, dy = event.clientY - start.y;
        start = null;
        if (Math.abs(dx) >= SWIPE_MIN && Math.abs(dx) > Math.abs(dy)) handler(dx > 0 ? 1 : -1);
    });
}
kit.swipeable = swipeable;
kit.roleCard = ({face = false, eyebrow = 'Твоя роль', title = '', side = '', faction = 'investigation', onOpen = null, onClose = null} = {}) => {
    const wrap = el('div', 'nc-cardwrap');
    if (!face) {
        const url = kit.art('card_back_role');
        const card = el('div', `nc-rolecard back${url ? '' : ' plain'}`);
        if (url) { const back = el('img'); back.src = url; back.alt = 'Рубашка карты роли'; card.append(back); }
        else card.append(attr(el('span', 'plain-back'), {'aria-hidden': 'true'}), kit.icon('seal'));
        if (onOpen) {
            // The whole back is a button: a tap or click, Enter or Space turns the card (a swipe that scrolls the page is no click).
            attr(card, {role: 'button', tabindex: '0', 'aria-expanded': 'false', 'aria-label': 'Рубашка карты роли. Открыть свою роль'});
            card.classList.add('tappable');
            let used = false;
            const turn = (dir = 1) => { if (used) return; used = true; kit.flip.dir = dir; attr(card, {'aria-expanded': 'true'}); onOpen(); };
            card.addEventListener('click', () => turn(1));
            swipeable(card, dir => turn(dir));
            card.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') { event.preventDefault?.(); turn(1); }
            });
        }
        wrap.append(card);
        return wrap;
    }
    // The emblem and frame are the world's art; without a pack the card is drawn by CSS and the emblem comes from the sprite.
    const emb = kit.icon(FACTIONS[faction]?.emblem || 'emblem_investigation', {alt: FACTIONS[faction]?.name || ''});
    emb.classList.add('emb');
    const frameUrl = kit.art('frame_hero');
    const frame = frameUrl ? Object.assign(el('img', 'frame'), {src: frameUrl, alt: ''}) : null;
    const body = put(el('div', 'body'), el('span', 'eyebrow', eyebrow), emb, el('h2', FACTIONS[faction]?.cls, title), side ? el('span', 'side', side) : null);
    const card = put(attr(el('article', `nc-rolecard${frame ? '' : ' plain'}`), {'aria-label': eyebrow}), el('div', 'face'), body, frame);
    if (frame) frameVars(card, 'hero');
    setVar(card, '--dir', String(kit.flip.dir)); kit.flip.dir = 1;
    if (onClose) { card.classList.add('swipe'); swipeable(card, () => onClose()); }
    wrap.append(card);
    return wrap;
};
/** Abilities list: [{icon, term, text}] */
kit.abilities = rows => put(el('div', 'nc-abil'), rows.map(row => put(el('div'), kit.icon(row.icon), put(el('p'), el('span', 'dt', row.term), rich(row.text, 'span', 'dd')))));

/** Portrait choice: {count, selected, taken: [n], onSelect(n)} — portraits taken by others are disabled. */
kit.portraits = ({count = kit.PORTRAITS, selected = null, taken = [], disabled = false, onSelect} = {}) => {
    const node = attr(el('div', 'nc-portraits'), {role: 'group', 'aria-label': 'Портрет за столом'});
    for (let n = 1; n <= count; n++) {
        const on = n === selected, busy = taken.includes(n) && !on;
        const button = attr(el('button', 'nc-portrait'), {'aria-pressed': String(on), 'aria-label': busy ? `Портрет ${n}: занят` : `Портрет ${n}`});
        button.type = 'button'; button.disabled = Boolean(disabled || busy);
        put(button, kit.avatar({portrait: n, me: on}), on ? withClass(kit.icon('check'), 'tick') : null);
        button.addEventListener('click', () => { if (!button.disabled && !on) onSelect?.(n); });
        node.append(button);
    }
    return node;
};

/* --- choice in two steps: pick here, confirm in the dock --- */
/** {items: [{id, name, sub, portrait, disabled}], selected, disabled, onSelect(id)} */
kit.picker = ({items = [], selected = null, disabled = false, onSelect, label = 'Выбор'} = {}) => {
    const node = attr(el('div', 'nc-picks'), {role: 'group', 'aria-label': label});
    for (const item of items) {
        const on = item.id === selected;
        const button = attr(el('button', 'nc-pick'), {'aria-pressed': String(on)}); button.type = 'button';
        button.disabled = Boolean(disabled || item.disabled);
        button.dataset.pick = item.id;
        put(button, kit.avatar({portrait: item.portrait}), on ? withClass(kit.icon('check'), 'tick') : null,
            put(el('span'), el('span', 'nm', item.name), item.sub ? rich(item.sub, 'span', 'sub') : null));
        button.addEventListener('click', () => { if (!button.disabled) onSelect?.(on ? null : item.id); });
        node.append(button);
    }
    return node;
};

/* --- records of a case: evidence (proof vs claim) and dossier --- */
/** {kind: 'proof' | 'claim', title, image (url), icon (a sign on the plate when there is no picture), meta, text,
 *  children (extra nodes under the text: buttons, a picker)} — proof: found by the server; claim: words, may be false. */
kit.evidence = ({kind = 'proof', title, image = null, icon = null, meta = '', text = '', children = []} = {}) => {
    const plate = el('div', `nc-evidence-plate${image ? '' : ' sign'}`);
    if (image) { const img = el('img', 'pic'); img.src = image; img.alt = ''; plate.append(img); }
    else if (icon) plate.append(kit.icon(icon));
    const frameUrl = kit.art('frame_evidence');
    const frame = frameUrl ? Object.assign(el('img', 'frame'), {src: frameUrl, alt: ''}) : null;
    const caption = put(el('figcaption'), el('span', `nc-evidence-kind ${kind}`, kind === 'claim' ? 'Утверждение' : 'Доказательство'),
        el('strong', null, title), meta ? rich(meta, 'span', 'meta') : null, text ? rich(text, 'p') : null, ...children);
    const art = put(el('div', `nc-evidence-art${frame ? '' : ' plain'}`), plate, frame);
    if (frame) frameVars(art, 'evidence');
    return put(el('figure', `nc-evidence ${kind}`), art, caption);
};
/** {eyebrow, title, portrait, facts: [[term, value]], text} */
kit.dossier = ({eyebrow = 'Досье', title, portrait = null, facts = [], text = ''} = {}) => {
    const frameUrl = kit.art('frame_dossier');
    const frame = frameUrl ? Object.assign(el('img', 'frame'), {src: frameUrl, alt: ''}) : null;
    const inner = put(el('div', 'nc-dossier-body'), el('span', 'nc-eyebrow', eyebrow), portrait != null ? kit.avatar({portrait}) : null,
        el('h2', 'nc-h3', title), facts.length ? put(el('dl'), facts.map(([term, value]) => [el('dt', null, term), rich(value, 'dd')])) : null,
        text ? rich(text, 'p', 'nc-note') : null);
    const card = put(attr(el('article', `nc-dossier${frame ? '' : ' plain'}`), {'aria-label': title}), inner, frame);
    if (frame) frameVars(card, 'dossier');
    return card;
};
/** «Ход дела»: [{icon, when, what}] */
kit.caseLog = (items, {title = 'Ход дела', note = 'роли скрыты до конца'} = {}) =>
    kit.panel({icon: 'papers', title, count: note}, put(el('ol', 'nc-log'), items.map(item =>
        put(el('li'), kit.icon(item.icon || 'papers'), put(el('div'), el('span', 'when', item.when), rich(item.what, 'span', 'what'))))));

/* --- discussion: messages are text; the composer keeps its draft across re-renders and reloads --- */
const draftMemory = new Map();
kit.drafts = {
    get(key) {
        if (draftMemory.has(key)) return draftMemory.get(key);
        try { return sessionStorage.getItem('nc-draft:' + key) || ''; } catch { return ''; }
    },
    set(key, value) {
        draftMemory.set(key, value);
        try { if (value) sessionStorage.setItem('nc-draft:' + key, value); else sessionStorage.removeItem('nc-draft:' + key); } catch { /* private mode */ }
    },
};
/** {messages: [{sys, icon} | {name, portrait, text, me}], composer: {key, enabled, onSend(text) → Promise<bool>, closed: [icon, text]}} */
kit.chat = ({title = 'Обсуждение', count = 'видят все за столом', messages = [], composer = null} = {}) => {
    const feed = el('div', 'nc-chat');
    for (const message of messages) {
        if (message.sys) { feed.append(put(el('div', 'nc-sys'), kit.icon(message.icon || 'sun'), message.sys)); continue; }
        const bubble = put(el('div', 'bub'), message.me ? null : el('span', 'who', message.name), el('p', null, message.text));
        feed.append(put(el('div', `nc-msg${message.me ? ' mine' : ''}`), message.me ? null : kit.avatar({portrait: message.portrait, size: 'sm'}), bubble));
    }
    if (!messages.length) feed.append(el('p', 'nc-note', 'Пока тихо. Начни разговор.'));
    let tail = null;
    if (composer?.enabled) {
        const input = attr(el('textarea', 'nc-field'), {rows: 1, maxlength: 1000, placeholder: 'Сообщение столу…', 'aria-label': 'Сообщение столу'});
        input.value = kit.drafts.get(composer.key);
        input.addEventListener('input', () => kit.drafts.set(composer.key, input.value));
        const send = kit.button('Отправить', async () => {
            const value = String(input.value || '');
            if (!value.trim()) { input.focus?.(); return; }
            kit.drafts.set(composer.key, value);
            send.disabled = true;
            const ok = await composer.onSend(value);
            if (ok) { kit.drafts.set(composer.key, ''); input.value = ''; }
            send.disabled = false;
        });
        tail = put(el('div', 'nc-compose'), input, send);
    } else if (composer?.closed) tail = kit.closed(...composer.closed);
    return kit.panel({icon: 'talk', title, count, cls: 'nc-chat-card'}, feed, tail);
};

/* --- music (docs/tasks/night_city/MUSIC_BRIEF.md §4) ---
   On by default at 15 % (owner, MQB-012 B2); the ⚙ menu has «Музыка» (on / off) and «Громкость музыки»; both are kept in localStorage (try / catch: no storage → defaults).
   Sound starts only after a user action: the menu tap itself, or, while it is on, the first tap anywhere.
   Track by place: the shell → one of the shell themes (random per session); a table → the world pack's `music`:
   lobby, day, voting → day; night → night (no night → day); the final → finale once, then silence (no finale → day).
   A loop is crossfaded with itself (two <audio> elements, 2.5 s, equal power) so there is no audible seam; a change of
   track is a 1.5 s crossfade. Tracks are fetched lazily, only for the current place and only while music is on; a load error
   means silence, the game goes on. A hidden tab pauses the music, coming back resumes it. prefers-reduced-motion does not touch sound.
   Volume goes through a GainNode (iOS ignores audio.volume); without Web Audio the element's volume is used. */
const MUSIC_KEY = 'nc-music';
const MUSIC_FADE = 1.5, MUSIC_FADE_OFF = 0.5, MUSIC_LOOP_FADE = 2.5;
const MUSIC_FILE = /^music_(day|night|finale)\.m4a$/, MUSIC_SHELL_FILE = /^music_shell_\d{1,2}\.m4a$/;

/** Slot of a world pack's `music` for a table status → 'day' | 'night' | 'finale' | null (pure). */
kit.musicSlot = (music, status) => {
    if (!music || typeof music !== 'object') return null;
    const has = slot => typeof music[slot]?.file === 'string' && music[slot].file === `music_${slot}.m4a`;
    const order = status === 'night' ? ['night', 'day'] : status === 'finished' ? ['finale', 'day'] : ['day', 'night'];
    return order.find(has) || null;
};

/** The player; `env` carries the platform (tests give fakes). */
function createMusic(env) {
    const prefs = {on: true, vol: 0.15};                      // owner's call (MQB-012 B2): on, quiet; a gesture still unlocks it
    try {
        const saved = JSON.parse(env.storage()?.getItem(MUSIC_KEY) || 'null');
        if (saved && typeof saved === 'object') {
            prefs.on = saved.on === true;
            if (typeof saved.vol === 'number' && saved.vol >= 0.05 && saved.vol <= 1) prefs.vol = saved.vol;
        }
    } catch { /* no storage, broken value: defaults */ }
    const legacy = {...prefs};
    const gain = () => prefs.vol * prefs.vol;                 // perceived loudness steps
    let scope = null;                                          // null | {shell: true} | {world, status}
    let unlocked = false, hidden = false, armed = false, finaleDone = false, shellPick = null;
    let audio = null, master = null;                           // Web Audio context and the master gain
    let playing = null;                                        // {key, track, cur, pre, voices[]}
    const leaving = [];                                        // voices fading out
    const failed = new Map();                                  // url → time of the last load error (retried after 60 s)
    let ticker = null, last = 0;

    /* ----- voices: one <audio> element with its gain ----- */
    const apply = voice => {
        if (voice.node) voice.node.gain.value = voice.level;
        else { try { voice.el.volume = Math.max(0, Math.min(1, voice.level * gain())); } catch { /* read-only volume */ } }
    };
    function makeVoice(url) {
        const el = env.makeAudio(url);
        const voice = {el, node: null, level: 0, fade: null, url};
        if (audio && master) {
            try { const source = audio.createMediaElementSource(el); voice.node = audio.createGain(); source.connect(voice.node); voice.node.connect(master); } catch { voice.node = null; }
        }
        apply(voice);
        el.addEventListener?.('error', () => { failed.set(url, env.now()); drop(voice, true); });
        el.addEventListener?.('ended', () => {
            const finale = playing && !playing.track.loop && playing.voices.includes(voice);
            dispose(voice);
            if (finale) { finaleDone = true; playing = null; }
            else if (playing?.track.loop && !playing.voices.length) { playing = null; reconcile(); }   // a lap ended before the crossfade ran: start again
        });
        return voice;
    }
    function play(voice) {
        let result;
        try { result = voice.el.play(); } catch { result = null; }
        result?.catch?.(error => {
            if (error?.name === 'AbortError') return;          // paused or replaced before it started
            if (error?.name === 'NotAllowedError') {
                if (playing?.voices.includes(voice)) {
                    drop(voice, false);
                    unlocked = false;
                    if (scope && prefs.on) arm();
                }
                return;
            }
            failed.set(voice.url, env.now()); drop(voice, true);
        });
    }
    function dispose(voice) {
        voice.fade = null;
        for (const list of [leaving, playing?.voices]) { const at = list ? list.indexOf(voice) : -1; if (at >= 0) list.splice(at, 1); }
        if (playing?.pre === voice) playing.pre = null;
        try { voice.el.pause(); voice.el.removeAttribute?.('src'); voice.el.load?.(); } catch { /* element gone */ }
        try { voice.node?.disconnect(); } catch { /* ignored */ }
        if (playing && playing.cur === voice) playing.cur = playing.voices[playing.voices.length - 1] || null;
    }
    /** A voice failed: the whole track goes silent (a loop partner shares the url). */
    function drop(voice, error) {
        if (playing && (playing.voices.includes(voice) || playing.pre === voice)) { for (const item of [...playing.voices, playing.pre].filter(Boolean)) dispose(item); playing = null; }
        else dispose(voice);
        if (error) reconcile();
    }
    function fadeTo(voice, to, seconds, done = null) {
        if (seconds <= 0 || Math.abs(voice.level - to) < 0.001) { voice.level = to; voice.fade = null; apply(voice); done?.(); return; }
        voice.fade = {from: voice.level, to, dur: seconds, t: 0, done};
        run();
    }
    function release(seconds) {
        if (!playing) return;
        const old = playing;
        playing = null;
        if (old.pre) { const pre = old.pre; old.pre = null; try { pre.el.pause(); pre.el.removeAttribute?.('src'); pre.node?.disconnect(); } catch { /* ignored */ } }
        for (const voice of old.voices) { leaving.push(voice); fadeTo(voice, 0, seconds, () => dispose(voice)); }
        old.voices = [];
    }

    /* ----- the clock: fades and the loop watch; stops itself when nothing plays ----- */
    function run() {
        if (ticker != null) return;
        last = env.now();
        ticker = env.setInterval(tick, 50);
    }
    function tick() {
        const now = env.now();
        const dt = Math.min(0.2, Math.max(0, (now - last) / 1000));
        last = now;
        if (hidden) return;
        for (const voice of [...leaving, ...(playing?.voices || [])]) {
            const fade = voice.fade;
            if (!fade) continue;
            fade.t += dt;
            const k = Math.min(1, fade.t / fade.dur);
            voice.level = fade.to >= fade.from ? fade.from + (fade.to - fade.from) * Math.sin(k * Math.PI / 2) : fade.to + (fade.from - fade.to) * Math.cos(k * Math.PI / 2);
            apply(voice);
            if (k >= 1) { voice.fade = null; fade.done?.(); }
        }
        const here = playing;
        if (here?.track.loop && here.cur) {
            const el = here.cur.el, left = el.duration - el.currentTime;
            if (Number.isFinite(left) && left <= 12 && !here.pre && !here.cur.crossed) here.pre = makeVoice(here.track.url);   // fetch the next lap early
            if (Number.isFinite(left) && left <= MUSIC_LOOP_FADE && !here.cur.crossed) loopCrossfade(here, Math.max(0.5, left));
        }
        if (!leaving.length && !playing && ticker != null) { env.clearInterval(ticker); ticker = null; }
    }
    function loopCrossfade(here, seconds) {
        const old = here.cur;
        old.crossed = true;
        const next = here.pre || makeVoice(here.track.url);
        here.pre = null;
        here.voices.push(next);
        here.cur = next;
        try { next.el.currentTime = 0; } catch { /* not seekable yet */ }
        play(next);
        fadeTo(next, 1, seconds);
        fadeTo(old, 0, seconds, () => dispose(old));
    }

    /* ----- which track, and the follow-up ----- */
    function wanted() {
        if (!scope) return null;
        if (scope.shell) {
            const list = env.shellMusic();
            if (list === null) { env.loadShell()?.then?.(loaded => { if (loaded) reconcile(); }); return null; }
            if (!list.length) return null;
            if (shellPick == null) shellPick = Math.min(list.length - 1, Math.floor(env.random() * list.length));
            return {key: `shell/${list[shellPick]}`, url: env.shellBase + list[shellPick], loop: true};
        }
        const pack = scope.world ? env.packOf(scope.world) : null;
        const slot = kit.musicSlot(pack?.music, scope.status);
        if (!slot) return null;
        if (slot === 'finale' && finaleDone) return null;
        const version = typeof pack.v === 'string' && pack.v ? '?v=' + pack.v : '';
        return {key: `${pack.id}/${slot}`, url: `${env.worldBase}${pack.id}/${pack.music[slot].file}${version}`, loop: slot !== 'finale'};
    }
    function reconcile() {
        let track = prefs.on && unlocked ? wanted() : null;
        if (track && env.now() - (failed.get(track.url) || -1e9) < 60000) track = null;
        if (hidden) { if (!track || playing?.key !== track.key) { release(0); sweep(); } return; }
        if (!track) { release(prefs.on ? MUSIC_FADE : MUSIC_FADE_OFF); return; }
        if (playing?.key === track.key) return;
        release(MUSIC_FADE);
        let voice;
        try { voice = makeVoice(track.url); } catch { failed.set(track.url, env.now()); return; }
        playing = {key: track.key, track, cur: voice, pre: null, voices: [voice]};
        play(voice);
        fadeTo(voice, 1, MUSIC_FADE);
    }
    const sweep = () => { for (const voice of [...leaving]) dispose(voice); };

    /* ----- gestures, tab visibility ----- */
    const gestures = ['pointerdown', 'touchend', 'keydown', 'click'];
    function onGesture() { unlock(); }
    function arm() {
        if (armed || !env.doc?.addEventListener) return;
        armed = true;
        for (const type of gestures) env.doc.addEventListener(type, onGesture, true);
    }
    function disarm() {
        if (!armed) return;
        armed = false;
        for (const type of gestures) env.doc.removeEventListener?.(type, onGesture, true);
    }
    /** Called from a user action: creates the audio context (it must be born in a gesture) and lets the music start. */
    function unlock() {
        if (unlocked) return;
        const AC = env.AudioContext();
        if (!audio && AC) {
            try { audio = new AC(); master = audio.createGain(); master.gain.value = gain(); master.connect(audio.destination); } catch { audio = master = null; }
        }
        try { audio?.resume?.(); } catch { /* ignored */ }
        unlocked = true;
        disarm();
        reconcile();
    }
    function onVisibility() {
        const now = Boolean(env.doc?.hidden);
        if (now === hidden) return;
        hidden = now;
        const voices = [...leaving, ...(playing?.voices || [])];
        if (hidden) { for (const voice of voices) { try { voice.el.pause(); } catch { /* ignored */ } } try { audio?.suspend?.(); } catch { /* ignored */ } return; }
        last = env.now();
        try { audio?.resume?.(); } catch { /* ignored */ }
        for (const voice of voices) play(voice);
        reconcile();
        if (voices.length) run();
    }
    let started = false;
    function init() {
        if (started) return;
        started = true;
        env.doc?.addEventListener?.('visibilitychange', onVisibility);
        hidden = Boolean(env.doc?.hidden);
    }

    return {
        get enabled() { return prefs.on; },
        get volume() { return prefs.vol; },
        applyPreferences(settings = {}) {
            prefs.on = settings.music ?? legacy.on;
            const volume = settings.music_volume == null ? legacy.vol : settings.music_volume / 100;
            if (volume !== prefs.vol) {
                prefs.vol = volume;
                if (master) master.gain.value = gain();
                for (const voice of [...leaving, ...(playing?.voices || [])]) apply(voice);
            }
            if (prefs.on && scope && !unlocked) arm();
            else disarm();
            reconcile();
        },
        /** Where the player is: null = silence, {shell: true}, {world, status}. Cheap to call on every screen. */
        follow(place) {
            init();
            const next = !place ? null : place.shell ? {shell: true} : {world: place.world || null, status: place.status || 'lobby'};
            if (scope?.world !== next?.world || next?.status !== 'finished') finaleDone = false;   // a new world or a new game plays its final again
            scope = next;
            if (scope && prefs.on && !unlocked) arm();
            else disarm();
            reconcile();
        },
        stop() { this.follow(null); },
        state() { return {on: prefs.on, vol: prefs.vol, unlocked, hidden, key: playing?.key ?? null, voices: (playing?.voices.length || 0) + leaving.length, finaleDone}; },
    };
}
kit.music = createMusic({
    storage: () => { try { return globalThis.localStorage || null; } catch { return null; } },
    AudioContext: () => globalThis.AudioContext || globalThis.webkitAudioContext || null,
    makeAudio: url => { const el = new globalThis.Audio(); el.preload = 'auto'; el.src = url; return el; },
    now: () => Date.now(),
    random: () => Math.random(),
    setInterval: (callback, ms) => { const handle = setInterval(callback, ms); handle?.unref?.(); return handle; },
    clearInterval: handle => clearInterval(handle),
    get doc() { return typeof document === 'object' ? document : null; },
    shellMusic: () => shellMusic,
    loadShell: () => kit.loadShell(),
    shellBase: SHELL_ART,
    worldBase: WORLD_ART,
    packOf: id => (skin.pack?.id === id ? skin.pack : null),
});
kit.createMusic = createMusic;
const syncMusicPreferences = () => kit.music.applyPreferences(window.QW?.prefs?.get?.().gamePreferences);
window.addEventListener?.('qw:game-preferences', syncMusicPreferences);
syncMusicPreferences();

/* --- the persistent game header: eyebrow + title, clock, ⚙ (one per page, the core owns ‹ and ⚙) --- */
let header = null;
kit.header = () => {
    if (header) return header;
    const node = el('header', 'nc-bar'), title = el('div', 'nc-title'), eyebrow = el('small'), name = el('h1');
    const slot = el('span', 'nc-clock-slot');
    title.append(eyebrow, name); node.append(title, slot);
    shell().header.mountBack?.(node); shell().header.mountGear?.(node);
    header = {node, set({eyebrow: small = 'Ночной город', title: text = 'Ночной город', clock = null} = {}) {
        // «Ночной город · Ночь 1»: the brand part may give way on a narrow phone when the clock needs the room (night-city.css)
        const brand = /^(Ночной город) · (.+)$/.exec(String(small));
        if (brand) eyebrow.replaceChildren(el('span', 'nc-brand', brand[1] + ' · '), el('span', null, brand[2])); else eyebrow.textContent = small;
        name.textContent = text; slot.replaceChildren(...(clock ? [clock] : []));
        node.classList.toggle?.('has-clock', Boolean(clock));
    }};
    return header;
};

/* ================= transport ================= */
class RequestError extends Error {}
async function http(path, {method = 'GET', body, key = null, channel = 'room', identity = null} = {}) {
    const url = channel === 'room' && identity ? `${path}${path.includes('?') ? '&' : '?'}identity=${identity}` : path;
    const headers = {};
    if (method !== 'GET') {
        headers['Content-Type'] = 'application/json';
        headers[channel === 'group' ? 'X-Mini-CSRF' : 'X-Guest-CSRF'] = '1';
        if (key) headers['Idempotency-Key'] = key;
    }
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 12000);
    try {
        const response = await fetch(url, {method, credentials: 'same-origin', headers, signal: controller.signal,
            ...(method === 'GET' ? {} : {body: JSON.stringify(body ?? {})})});
        if (response.status === 204) return null;
        let data = null; try { data = await response.json(); } catch { /* not JSON */ }
        if (!response.ok) {
            const error = new RequestError(typeof data?.detail === 'string' ? data.detail : 'Сервис временно недоступен. Повтори позже.');
            error.status = response.status; error.data = data || {}; if (typeof data?.code === 'string') error.code = data.code;
            throw error;
        }
        if (data == null) { const error = new RequestError('Сервис временно недоступен. Повтори позже.'); error.status = response.status; throw error; }
        return data;
    } catch (error) {
        if (error instanceof RequestError) throw error;
        const lost = new RequestError('Нет связи с приложением. Проверь подключение.'); lost.network = true; throw lost;
    } finally { clearTimeout(timer); }
}
const uuid = () => globalThis.crypto?.randomUUID?.() || `nc-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
const uncertain = error => error.network || !error.status || error.status >= 500;

/* ================= links and invitation codes ================= */
const CODE = /^[A-Za-z0-9_-]{4,64}$/;
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
/** start_param / ?room / pasted text → {roomId} | {code} | null. roomid_ is checked before room_. */
function parseLaunch(raw) {
    const value = String(raw || '').trim();
    if (!value) return null;
    if (value.startsWith('roomid_')) return UUID.test(value.slice(7)) ? {roomId: value.slice(7).toLowerCase()} : null;
    if (value.startsWith('room_')) return CODE.test(value.slice(5)) ? {code: value.slice(5)} : null;
    return null;
}
/** What a player pastes into «Войти по приглашению»: a code, room_<code>, a t.me link or <origin>/app#room=<code> (the older ?room=<code> too). */
function parseInvite(text) {
    let value = String(text || '').trim();
    if (!value) return null;
    if (/^(https?:\/\/|t\.me\/)/i.test(value)) {
        try {
            const url = new URL(/^https?:/i.test(value) ? value : 'https://' + value);
            const room = (/(?:^#|&)room=([^&]*)/.exec(String(url.hash || '')) || [])[1] || url.searchParams.get('room');
            if (room && CODE.test(room)) return {code: room};
            const start = url.searchParams.get('startapp') || url.searchParams.get('tgWebAppStartParam') || url.searchParams.get('start');
            return parseLaunch(start);
        } catch { return null; }
    }
    const launched = parseLaunch(value);
    if (launched) return launched;
    value = value.replace(/\s+/g, '');
    if (TOKEN.test(value)) return {code: value};
    return CODE.test(value) ? {short: value} : null;
}

/* ================= app ================= */
const ROLES = {
    mafia: {title: 'Мафия', you: 'Ты — мафия', faction: 'shadow', icon: 'emblem_shadow', side: 'Играешь за мафию', cls: 'nc-role-mafia',
        about: 'Ночью вместе с напарниками выбираешь, кого убрать из игры. Днём — не выдать себя.',
        rows: [['moon', 'Ночью', 'выбираешь цель вместе с мафией'], ['sun', 'Днём', 'обсуждаешь и голосуешь, не выдавая себя'], ['laurel', 'Победа', 'мафии за столом не меньше, чем мирных']]},
    detective: {title: 'Детектив', you: 'Ты — детектив', faction: 'investigation', icon: 'lens', side: 'Играешь за город', cls: 'nc-role-town',
        about: 'Каждую ночь проверяешь одного игрока. Утром узнаешь: мафия он или нет.',
        rows: [['moon', 'Ночью', 'выбираешь, кого проверить'], ['sun', 'Днём', 'обсуждаешь и голосуешь — можешь намекнуть, но тебя услышит и мафия'], ['laurel', 'Победа', 'город выводит всю мафию']]},
    doctor: {title: 'Доктор', you: 'Ты — доктор', faction: 'investigation', icon: 'vial', side: 'Играешь за город', cls: 'nc-role-town',
        about: 'Каждую ночь защищаешь одного игрока. Если мафия выберет его, он останется в игре.',
        rows: [['moon', 'Ночью', 'выбираешь, кого защитить'], ['sun', 'Днём', 'обсуждаешь и голосуешь'], ['laurel', 'Победа', 'город выводит всю мафию']]},
    citizen: {title: 'Мирный житель', you: 'Ты — мирный житель', faction: 'investigation', icon: 'house', side: 'Играешь за город', cls: 'nc-role-town',
        about: 'Ночью хода нет. Твоё оружие — обсуждение и голос.',
        rows: [['moon', 'Ночью', 'спишь — хода нет'], ['sun', 'Днём', 'обсуждаешь и голосуешь'], ['laurel', 'Победа', 'город выводит всю мафию']]},
};
const PHASE_SECONDS = {night: 90, day: 180, voting: 90};
const PHASES = [{id: 'night', label: 'Ночь', icon: 'moon'}, {id: 'day', label: 'День', icon: 'sun'}, {id: 'voting', label: 'Голосование', icon: 'scales'}];
const RULES = [
    ['people', 'Стол', 'От 4 до 12 игроков. Ведущий — приложение: роли раздаёт сервер, каждому тайно.'],
    ['moon', 'Ночь', 'Мафия выбирает цель, доктор защищает, детектив проверяет одного игрока.'],
    ['sun', 'День', 'Утром становится известно, кто выбыл. Стол обсуждает, кто мог это сделать.'],
    ['scales', 'Голосование', 'Голос тайный. Выбывает тот, у кого больше всех голосов; при ничьей — никто.'],
    ['laurel', 'Победа', 'Город — когда вся мафия выведена. Мафия — когда её не меньше, чем мирных.'],
];
const OPEN_ROOMS = '/api/guest/rooms/open';          // NIGHT_CITY_OPEN_ROOMS: the section hides while the route is absent
const pendingCommands = new Map();                    // table key → {path, body, key, label}: an answer lost on the way
const createdInvites = new Map();                     // room id → last created invitation (the code is shown only once)
const pickedTargets = new Map();                      // table key + phase revision → seat chosen but not confirmed
const confirmedTargets = new Map();                   // table key + phase revision → name chosen and accepted
const seenRole = new Set();                           // table key + first night revision → card turned face up

function open(options) {
    const Q = shell();
    const gm = options.gm || ((m, f, n) => n);
    const identity = options.identity || null;
    const token = {};
    let current = token;
    const ctx = {token, view: 'entry', room: null, group: null, data: null, overlay: null, notice: null, net: false, timer: null, poll: null, busy: false, fingerprint: '', worldWanted: null, worldPick: null, worldIndex: undefined, ageAsk: null};
    NightCity.close = () => { current = null; ctx.timer?.stop(); kit.music.stop(); kit.useWorld(null); document.documentElement?.classList?.remove?.('nc'); };
    const alive = () => current === token && options.isCurrent();
    const host = options.host;
    document.documentElement?.classList?.add?.('nc');
    const bar = kit.header();
    kit.loadShell();
    const request = (path, init = {}) => http(path, {...init, identity, channel: init.channel || 'room'});

    /* ---------- frame ---------- */
    function frame({eyebrow, title, clock = null, main = [], dock = null, scene = {}, net = false}) {
        if (!alive()) return;
        followMusic();
        bar.set({eyebrow, title, clock});
        kit.pageScene(scene);
        const body = put(el('div', `nc-main${dock ? ' has-dock' : ''}`), main);
        // A notice and an open confirmation (leave, remove) sit right under the scene, on every table screen.
        const notes = [ctx.notice ? kit.alert({tone: ctx.notice.tone || 'warn', icon: ctx.notice.icon || 'alert', title: ctx.notice.text}) : null,
            ctx.view === 'table' ? ctx.leaveConfirm : null].filter(Boolean);
        for (const note of notes.reverse()) body.insertBefore(note, body.children[1] || null);
        host.replaceChildren(...[bar.node, net ? kit.netBanner({onRetry: () => refresh(true)}) : null, body, dock].filter(Boolean));
        host.dataset.page = 'night';
    }
    /** The player follows the screen: the shell theme outside a table, the world's track by phase at one (silence while the world is unknown). */
    function followMusic() {
        const lobby = ctx.view === 'table' ? ctx.data?.lobby : null;
        kit.music.follow(lobby ? {world: kit.world, status: lobby.status} : {shell: true});
    }
    function menu(items) { Q.menu.register(items.filter(Boolean), 'Ночной город'); }
    // Menu glyphs come from the shell's vector sprite, never from a world's art.
    const menuIcon = name => `<use href="${SHELL_ART}icons.svg#nc-i-${name}"/>`;
    const rulesItem = () => ({id: 'nc-rules', label: 'Правила дела', hint: 'роли, фазы, кто побеждает', icon: menuIcon('papers'), onSelect: () => showOverlay('rules')});

    /* ---------- the world of the table: loaded lazily, applied when ready ---------- */
    /** Loads the pack of a world and applies it. Waits for the art only briefly: a slower pack re-skins the table when it arrives,
        a failed one leaves the shell's vector scene. The table works either way. */
    function ensureWorld(id) {
        const want = WORLD_ID.test(String(id)) ? id : DEFAULT_WORLD;
        if (kit.world === want) return Promise.resolve();
        ctx.worldWanted = want;
        const loading = kit.loadPack(want).then(pack => {
            if (!alive() || ctx.worldWanted !== want) return false;
            const changed = kit.world !== (pack?.id ?? null);
            kit.useWorld(pack);
            return changed;
        });
        return within(loading, 1500).then(done => {
            if (done !== undefined) return;
            loading.then(changed => {
                if (!changed || !alive() || ctx.view !== 'table') return;
                if (document.activeElement?.tagName === 'TEXTAREA' && host.contains?.(document.activeElement)) return;   // the next poll re-skins
                ctx.fingerprint = ''; render();
            });
        });
    }

    /* ---------- overlays (role card, rules): one entry in the back stack ---------- */
    function showOverlay(kind) {
        ctx.overlay = kind;
        Q.nav.push?.({id: 'nc-' + kind, onBack: () => { if (kind === 'age') ageBack(); else { ctx.overlay = null; render(); } return true; }});
        render();
    }
    /* ---------- 18+ worlds: one question before entering or choosing; the answer is remembered on this device only ---------- */
    const AGE_KEY = 'nc-age18-ok';
    const age18Known = () => { try { return globalThis.localStorage?.getItem(AGE_KEY) === '1'; } catch { return false; } };   // no storage: asked every time
    const age18Remember = () => { try { globalThis.localStorage?.setItem(AGE_KEY, '1'); } catch { /* private mode */ } };
    /** Asks «Тебе есть 18?»; onYes runs the action again with age_ok. «Назад» returns to where the player was (the list or the world picker). */
    function askAge18(onYes, world = null) {
        ctx.ageAsk = {onYes, world, returnTo: ctx.overlay === 'age' ? null : ctx.overlay};
        showOverlay('age');
    }
    function ageBack() { const ask = ctx.ageAsk; ctx.ageAsk = null; ctx.overlay = ask?.returnTo ?? null; render(); }
    function ageYes() {
        const ask = ctx.ageAsk; ctx.ageAsk = null; age18Remember();
        ctx.overlay = ask?.returnTo ?? null; Q.nav.pop?.('nc-age');
        ask?.onYes?.();
    }
    function renderAgeGate() {
        // The story in question, when it is known: its cover, name and the 18+ plaque, so the question is about something concrete.
        const entry = ctx.ageAsk?.world ? kit.worldEntry(ctx.ageAsk.world) : null;
        const thumb = entry ? kit.thumbUrl(entry) : '';
        const story = entry ? kit.panel({icon: 'story', title: 'Сюжет'}, put(el('div', `nc-story${thumb ? '' : ' nothumb'}`), thumb ? Object.assign(el('img'), {src: thumb, alt: ''}) : null,
            put(el('div'), put(el('strong'), entry.title, ageBadge(18)), entry.era ? el('span', null, entry.era) : null))) : null;
        frame({eyebrow: 'Ночной город · Для взрослых', title: ctx.view === 'table' ? tableTitle() : 'Ночной город', scene: {shell: 'invite'}, main: [
            kit.scene({shell: 'invite', size: 'tall', eyebrow: put(el('span', 'nc-age-plate'), ageBadge(18)), title: 'Только для взрослых', text: 'В этом сюжете есть сцены для взрослых. Тебе есть 18?'}),
            story ? put(el('div', 'nc-span nc-col'), story) : null],
            dock: kit.dock({layout: 'row', hint: 'Ответ запомнится на этом устройстве', buttons: [kit.button('Назад', () => { Q.nav.pop?.('nc-age'); ageBack(); }), kit.button('Мне есть 18', () => ageYes(), {kind: 'primary'})]})});
    }
    function dropOverlay() { const kind = ctx.overlay; ctx.overlay = null; if (kind) Q.nav.pop?.('nc-' + kind); }
    function closeOverlay() { dropOverlay(); render(); }

    /* ================= entry ================= */
    async function showEntry(message = null) {
        stopTable(); ctx.view = 'entry'; ctx.room = ctx.group = ctx.data = null; ctx.notice = message;
        kit.useWorld(null); ctx.worldWanted = null;     // the shell has no world
        Q.nav.setRoot(null);
        menu([rulesItem()]);
        const rooms = kit.panel({icon: 'calendar', title: 'Твои комнаты'}, kit.note('Загружаем…'));
        const tables = el('div', 'nc-open-slot');
        const join = kit.panel({icon: 'key', title: 'Войти по приглашению'},
            kit.joinField({onSubmit: (text, button) => joinByText(text, button)}),
            kit.note('Код или ссылку присылает хозяин комнаты.'));
        frame({eyebrow: 'Ночной город · Дело 01', title: 'Ночной город', scene: {shell: 'rooms'}, main: [
            kit.scene({shell: 'entry', size: 'tall', eyebrow: 'Мафия · 4–12 игроков', title: 'Город засыпает',
                text: 'Роли тайные, ведущий — приложение. Партия около 20 минут.',
                body: kit.stack(kit.button('Собрать компанию', gatherCompany, {kind: 'primary', icon: 'people', crumb: 'nc-gather'}))}),
            put(el('div', 'nc-col'), join, rooms),
            put(el('div', 'nc-col'), tables, groupPanel()),
        ]});
        const [mine, open, index] = await Promise.allSettled([request('/api/guest/rooms'), request(OPEN_ROOMS), kit.worldIndex()]);
        if (!alive() || ctx.view !== 'entry') return;
        const chip = (id, age) => kit.worldChip(index.status === 'fulfilled' ? kit.worldEntry(id) : null, age);   // chips only when the index is known
        rooms.replaceChildren(...roomsPanel(mine, chip).children);
        if (open.status === 'fulfilled' && Array.isArray(open.value?.items)) tables.replaceChildren(openTablesPanel(open.value.items, chip));
    }
    function roomsPanel(result, chip = () => null) {
        if (result.status === 'rejected') return kit.panel({icon: 'calendar', title: 'Твои комнаты'}, kit.note(result.reason.message, 'nc-note error'),
            kit.row(kit.button('Повторить', () => showEntry(), {compact: true})));
        const items = result.value?.items || [];
        const list = el('ul', 'nc-list');
        for (const room of items) {
            const state = room.mafia_status || room.game_status || null;   // optional summary; shown only when the server sends it
            const meta = [room.role === 'owner' ? 'ты хозяин комнаты' : room.owner_name ? `хозяин ${room.owner_name}` : 'ты в комнате',
                Number.isFinite(room.players) ? `${room.players} за столом` : null].filter(Boolean).join(' · ');
            const badge = chip(room.world, room.world_age);
            const copy = put(el('div'), el('span', 'ttl', room.title || 'Комната'), el('span', 'meta', meta),
                state || badge ? put(el('div', 'tags'), badge, state ? kit.tag(state === 'lobby' ? 'собирается' : 'идёт партия', {tone: state === 'lobby' ? '' : 'amber', icon: state === 'lobby' ? null : 'moon'}) : null) : null);
            list.append(put(el('li', 'qw-action-row'), copy, kit.button(state && state !== 'lobby' ? 'Вернуться' : 'Открыть', () => openRoom(room), {compact: true})));
        }
        if (!items.length) list.append(put(el('li', 'nc-empty'), kit.shellPicture('empty'), el('span', null, 'Комнат пока нет. Собери компанию или войди по приглашению.')));
        return kit.panel({icon: 'calendar', title: 'Твои комнаты', count: items.length ? String(items.length) : ''}, list);
    }
    /** Open tables: [{room_id, title, host_name, seated, waiting, needs_from, capacity, status: gathering|playing|full, joined}] */
    function openTablesPanel(items, chip = () => null) {
        const list = el('ul', 'nc-list');
        for (const table of items) {
            const seated = Number(table.seated) || 0, capacity = Number(table.capacity) || 12;
            const full = table.status === 'full', playing = table.status === 'playing';
            const meta = [table.host_name ? `хозяин ${table.host_name}` : null,
                full || seated >= capacity ? `сидит ${seated} из ${capacity}` : `сидит ${seated} · нужно от ${table.needs_from || 4}`,
                Number(table.waiting) ? `ждут ${table.waiting}` : null].filter(Boolean).join(' · ');
            const copy = put(el('div'), el('span', 'ttl', table.title || 'Стол'), el('span', 'meta', meta),
                put(el('div', 'tags'), chip(table.world, table.world_age), kit.tag(full ? 'стол полон' : playing ? 'идёт партия' : 'собирается', {tone: full ? '' : playing ? 'amber' : 'ok', icon: playing ? 'moon' : null})));
            const action = table.joined ? kit.button('Открыть', () => openRoom({id: table.room_id, title: table.title, role: 'member', world: table.world}), {compact: true})
                : full ? el('span', 'end-note', 'мест нет')
                    : kit.button(playing ? 'Ждать следующую' : 'Сесть за стол', event => joinOpenTable(table, event.currentTarget), {compact: true});
            list.append(put(el('li', 'qw-action-row'), copy, action));
        }
        if (!items.length) list.append(put(el('li', 'nc-empty'), kit.shellPicture('empty'), el('span', null, 'Открытых столов сейчас нет.')));
        return kit.panel({icon: 'table', title: 'Открытые столы', count: 'сесть может любой'}, list);
    }
    /** Sits at the table of an open room without a code, or waits for the next game while one is running. */
    async function joinOpenTable(table, button, confirmed = false) {
        const adult = kit.worldAge(table.world, table.world_age) >= 18;
        if (adult && !confirmed && !age18Known()) { askAge18(() => joinOpenTable(table, null, true), table.world); return; }
        if (button) button.disabled = true;
        try {
            const result = await request(`/api/guest/rooms/${encodeURIComponent(table.room_id)}/join-open`, {method: 'POST', body: adult || confirmed ? {age_ok: true} : {}, key: uuid()});
            if (alive()) openRoom(result?.room || {id: table.room_id, title: table.title, role: 'member', world: table.world});
        } catch (error) {
            if (!alive()) return;
            if (error.code === 'age_confirm_required' && !confirmed) { if (age18Known()) joinOpenTable(table, null, true); else askAge18(() => joinOpenTable(table, null, true), table.world); return; }
            showEntry({text: error.message});
        }
    }
    function groupPanel() {
        const groups = options.groups || [];
        const steps = put(el('ol', 'nc-steps-list'), put(el('li'), el('span', null, 'Добавь бота в группу друзей.')),
            put(el('li'), rich(['Напиши в группе ', put(el('code'), '/mafia'), ' — стол соберётся прямо в чате, роли придут в личку.'])));
        const GROUP_STATE = {gathering: ['стол собирается', 'ok', null], playing: ['идёт партия', 'amber', 'moon'], full: ['стол полон', '', null], finished: ['партия закончилась', '', null]};
        const list = groups.length ? put(el('ul', 'nc-list'), groups.map(group => {
            const table = group.mafia || {}, state = GROUP_STATE[table.status];
            const meta = ['группа · бот уже там', Number(table.seated) ? `за столом ${table.seated}` : null, table.joined ? 'ты за столом' : null].filter(Boolean).join(' · ');
            return put(el('li', 'qw-action-row'),
                put(el('div'), el('span', 'ttl', group.title || 'Группа'), el('span', 'meta', meta), state ? put(el('div', 'tags'), kit.tag(state[0], {tone: state[1], icon: state[2]})) : null),
                kit.button(table.joined ? 'Вернуться' : 'Открыть стол', () => openGroup(group), {compact: true}));
        })) : null;
        const add = options.botUsername ? kit.row(kit.button('Добавить бота в группу', () => openLink(`https://t.me/${options.botUsername}?startgroup=mafia`))) : null;
        return kit.panel({icon: 'hands', title: 'Играть в Telegram-группе'}, steps, list, add);
    }
    function openLink(url) {
        const tg = options.telegram?.();
        try { if (tg?.openTelegramLink && /^https:\/\/t\.me\//.test(url)) { tg.openTelegramLink(url); return; } } catch { /* fall back */ }
        window.open?.(url, '_blank', 'noopener,noreferrer');
    }
    let gathering = false;
    async function gatherCompany() {
        if (gathering) return;
        gathering = true; ctx.notice = null;
        try {
            const data = await request('/api/guest/rooms');
            let room = (data.items || []).find(item => item.role === 'owner' && item.title === 'Ночной город');
            if (!room) room = await request('/api/guest/rooms', {method: 'POST', body: {request_id: uuid(), title: 'Ночной город'}});
            if (alive()) await openRoom({...room, role: 'owner'});
        } catch (error) { if (alive()) showEntry({text: error.message}); }
        finally { gathering = false; }
    }
    async function joinByText(text, button) {
        const parsed = parseInvite(text);
        if (!parsed) { ctx.notice = {text: 'Не похоже на код приглашения. Вставь код или ссылку целиком.'}; return showEntry(ctx.notice); }
        if (button) button.disabled = true;
        await launch(parsed);
    }

    /* ================= launch: room_<code>, roomid_<uuid>, #room=<code> / ?room=<code>, mafia_n<chat> ================= */
    async function launch(target, ageOk = false) {
        if (target?.room) return openRoom(target.room);
        if (target?.code || target?.short) {
            try {
                const room = await request('/api/guest/rooms/join', {method: 'POST', body: {...(target.code ? {invite_code: target.code} : {short_code: target.short}), ...(ageOk ? {age_ok: true} : {})}});
                if (alive()) await openRoom(room, {sit: true});
            } catch (error) {
                if (!alive()) return;
                if (error.code === 'age_confirm_required' && !ageOk) {      // the room is an 18+ story: ask once, then enter
                    if (age18Known()) launch(target, true); else askAge18(() => launch(target, true));
                    return;
                }
                // A typed code that matches nothing is a typo; a dead link or a known-but-spent code gets the expired screen.
                if (error.status === 410 || (error.status === 404 && target.code)) showExpired(error);
                else showEntry({text: error.message});
            }
            return;
        }
        if (target?.roomId) {
            try { const room = await request(`/api/guest/rooms/${encodeURIComponent(target.roomId)}`); if (alive()) await openRoom(room); }
            catch (error) { if (alive()) showEntry({text: error.status === 404 ? 'Эта комната недоступна: тебя нет среди её участников.' : error.message}); }
            return;
        }
        if (target?.chatId) {
            const group = (options.groups || []).find(item => String(item.chat_id) === String(target.chatId));
            if (group) return openGroup(group);
            return showEntry({text: 'Стол этой группы недоступен: бот или ты больше не в ней.'});
        }
        return showEntry();
    }
    function showExpired(error) {
        const title = error?.data?.room_title, reason = error?.data?.reason;
        const detail = title ? {expired: `Срок приглашения в «${title}» истёк.`, used: `Приглашение в «${title}» уже использовали все, кому оно было.`,
            revoked: `Хозяин «${title}» отозвал это приглашение.`, exhausted: `Приглашение в «${title}» уже использовали все, кому оно было.`}[reason] || `Приглашение в «${title}» больше не действует.` : error?.message;
        stopTable(); ctx.view = 'expired'; ctx.notice = null; Q.nav.setRoot(() => showEntry());
        kit.useWorld(null); ctx.worldWanted = null;
        menu([rulesItem()]);
        frame({eyebrow: 'Ночной город · Приглашение', title: 'Ночной город', scene: {shell: 'invite'}, main: [
            kit.scene({shell: 'invite', eyebrow: 'Приглашение', title: 'Ссылка больше не работает',
                text: `${detail || 'Приглашение больше не действует.'} Попроси у хозяина комнаты новую ссылку — или садись за другой стол.`}),
            put(el('div', 'nc-col'),
                kit.panel({icon: 'key', title: 'Есть новый код?'}, kit.joinField({onSubmit: (text, button) => joinByText(text, button)})),
                kit.panel({icon: 'people', title: 'Или своя компания'}, kit.note('Создадим комнату и дадим ссылку, которую можно отправить друзьям.', 'nc-muted'),
                    kit.stack(kit.button('Собрать компанию', gatherCompany, {kind: 'primary'})))),
        ]});
    }

    /* ================= a table: room (account-owned) or Telegram group ================= */
    function tableKey() { return ctx.room ? 'room:' + ctx.room.id : 'group:' + ctx.group.chat_id; }
    function base() { return ctx.room ? `/api/guest/rooms/${encodeURIComponent(ctx.room.id)}/mafia` : `/api/mini/mafia/chats/${ctx.group.chat_id}`; }
    const channel = () => (ctx.room ? 'room' : 'group');
    function stopTable() { ctx.timer?.stop(); ctx.timer = null; ctx.poll = null; ctx.overlay = null; ctx.fingerprint = ''; ctx.leaveConfirm = null; }
    async function openRoom(room, {sit = false} = {}) {
        stopTable(); ctx.view = 'table'; ctx.room = room; ctx.group = null; ctx.notice = null; ctx.sit = sit;
        Q.nav.setRoot(() => showEntry());
        ensureWorld(room.world);
        frame({eyebrow: 'Ночной город · Комната', title: room.title || 'Комната', scene: {shell: 'loading'}, main: [loadingScene('Комната')]});
        await refresh(true);
    }
    async function openGroup(group) {
        stopTable(); ctx.view = 'table'; ctx.group = group; ctx.room = null; ctx.notice = null; ctx.sit = false;
        Q.nav.setRoot(() => showEntry());
        ensureWorld(DEFAULT_WORLD);
        frame({eyebrow: 'Ночной город · Telegram-группа', title: group.title || 'Группа', scene: {shell: 'loading'}, main: [loadingScene('Telegram-группа')]});
        await refresh(true);
    }
    /** The shell's «loading» picture while the table and its world arrive (the street lamp), not an empty page. */
    function loadingScene(eyebrow) {
        return attr(kit.scene({shell: 'loading', size: 'tall nc-loading-scene', eyebrow, title: 'Открываем стол…'}), {'aria-busy': 'true'});
    }
    /** Loads the table; a lost command is retried first with the same Idempotency-Key. */
    async function refresh(force = false) {
        if (!alive() || ctx.view !== 'table') return;
        const key = tableKey(), lost = pendingCommands.get(key), here = () => alive() && ctx.view === 'table' && tableKey() === key;
        const recovering = ctx.net;
        if (lost) {
            try { await request(lost.path, {method: 'POST', body: lost.body, key: lost.key, channel: channel()}); pendingCommands.delete(key); ctx.net = false; lost.onAccepted?.(); }
            catch (error) {
                if (!here()) return;
                if (uncertain(error)) { ctx.net = true; render(); schedule(); return; }
                pendingCommands.delete(key); ctx.notice = {text: error.message};
            }
        }
        try {
            let lobby = (await request(`${base()}/lobby`, {channel: channel()})).lobby;
            if (!here()) return;
            if (!lobby && ctx.room?.role === 'owner') lobby = (await request(`${base()}/lobby`, {method: 'POST', body: {}, key: uuid()})).lobby;
            if (lobby && !lobby.joined && lobby.status === 'lobby' && ctx.sit) { ctx.sit = false; lobby = (await request(`${base()}/lobby/join`, {method: 'POST', body: {}, key: uuid(), channel: channel()})).lobby; }
            const [role, talk] = await Promise.all([
                lobby?.joined && lobby.status !== 'lobby' ? request(`${base()}/role`, {channel: channel()}).catch(error => (error.status === 409 ? null : Promise.reject(error))) : null,
                lobby?.joined ? request(`${base()}/discussion`, {channel: channel()}).catch(() => null) : null,
            ]);
            if (!here()) return;
            await ensureWorld(lobby?.world || ctx.room?.world);
            if (!here()) return;
            ctx.net = false;
            const next = {lobby, role, talk};
            const print = JSON.stringify([lobby && {...lobby, server_now: 0}, role, talk?.items?.length, talk?.enabled, ctx.notice?.text, ctx.overlay, kit.world]);
            ctx.data = next;
            if (force || recovering || print !== ctx.fingerprint) {
                // Never pull the field from under a player who is typing; the draft is kept anyway.
                if (!force && !recovering && document.activeElement?.tagName === 'TEXTAREA' && host.contains?.(document.activeElement)) { schedule(); return; }
                ctx.fingerprint = print; render();
            }
        } catch (error) {
            if (!here()) return;
            if (uncertain(error)) { ctx.net = true; render(); }
            else if (error.status === 404 || error.status === 403) { showEntry({text: error.message}); return; }
            else { ctx.notice = {text: error.message}; render(); }
        }
        schedule();
    }
    function schedule() {
        if (!alive() || ctx.view !== 'table') return;
        const handle = {};
        ctx.poll = handle;
        later(() => { if (ctx.poll === handle) refresh(); }, ctx.net ? 3000 : 4000);
    }
    /** Every table command: one at a time, an uncertain one is kept and retried with the same key. */
    async function command(suffix, body, label, button = null, {onAccepted = null, room = false} = {}) {
        const key = tableKey(), path = `${room && ctx.room ? `/api/guest/rooms/${encodeURIComponent(ctx.room.id)}` : base()}${suffix}`;
        const lost = pendingCommands.get(key);
        if (lost && (lost.path !== path || JSON.stringify(lost.body) !== JSON.stringify(body))) {
            ctx.notice = {text: 'Сначала дождись результата прошлого действия: проверяем его.'}; render(); return false;
        }
        const entry = lost || {path, body, key: uuid(), label, onAccepted};
        pendingCommands.set(key, entry);
        if (button) button.disabled = true;
        try {
            await request(path, {method: 'POST', body, key: entry.key, channel: channel()});
            pendingCommands.delete(key); ctx.notice = null; ctx.net = false;
            onAccepted?.();
            if (alive()) await refresh(true);
            return true;
        } catch (error) {
            if (!alive() || ctx.view !== 'table') return false;
            if (uncertain(error)) { ctx.net = true; render(); schedule(); }
            else { pendingCommands.delete(key); ctx.notice = {text: error.message}; await refresh(true); }
            if (button) button.disabled = false;
            return false;
        }
    }

    /* ================= render: mafia test game as a thin layer over the kit ================= */
    function render() {
        if (!alive()) return;
        if (ctx.overlay === 'age') return renderAgeGate();
        if (ctx.overlay === 'rules') return renderRules();
        if (ctx.view === 'entry') return showEntry(ctx.notice);
        if (ctx.view !== 'table') return;
        if (!ctx.data) {
            const lost = pendingCommands.get(tableKey());
            return frame({eyebrow: 'Ночной город', title: tableTitle(), scene: {slot: 'vote'}, net: ctx.net, main: [
                kit.alert({icon: 'hourglass', title: lost ? `${lost.label} — ответ не дошёл` : 'Нет связи со столом',
                    text: 'Когда связь вернётся, проверим сами — второй раз действие не засчитается.',
                    actions: [kit.button('Проверить сейчас', () => refresh(true), {compact: true})]})]});
        }
        const {lobby, role} = ctx.data;
        if (ctx.overlay === 'role' && role) return renderRoleFace(role);
        if (ctx.overlay === 'portrait' && lobby?.status === 'lobby') return renderPortrait(lobby);
        if (ctx.overlay === 'world' && lobby?.status === 'lobby' && lobby.is_host && ctx.room) return renderWorldPicker(lobby);
        if (!lobby) return renderNoTable();
        menu(tableMenu(lobby));
        if (lobby.status === 'lobby' || !lobby.joined) return renderLobby(lobby);
        if (role && lobby.status === 'night' && lobby.round === 1 && role.alive && !seenRole.has(`${tableKey()}:${lobby.phase_revision}`)) return renderRoleBack(lobby);
        if (lobby.status === 'finished') return renderFinal(lobby, role);
        if (role && !role.alive) return renderOut(lobby, role);
        if (lobby.status === 'night') return renderNight(lobby, role);
        if (lobby.status === 'day') return renderDay(lobby, role);
        return renderVote(lobby, role);
    }
    const tableTitle = () => ctx.room?.title || ctx.group?.title || 'Стол';
    const seatName = (lobby, seat) => lobby.players.find(player => player.seat === seat)?.name || 'игрок';
    const portraitOf = player => player.portrait ?? (Number(String(player.seat || 'p1').slice(1)) || 1);
    const me = lobby => lobby.players.find(player => player.is_me) || null;
    function tableMenu(lobby) {
        const owner = ctx.room?.role === 'owner';
        return [
            canPickWorld(lobby) ? {id: 'nc-world', label: 'Сюжет комнаты', hint: `${worldTitle(lobby.world || DEFAULT_WORLD) || 'выбрать'} · сменить до партии`, icon: menuIcon('story'), onSelect: () => openWorldPicker()} : null,
            owner ? {id: 'nc-invite', label: 'Пригласить', hint: 'код и ссылка на этот стол', icon: menuIcon('envelope'), onSelect: () => issueInvite()} : null,
            rulesItem(),
            ctx.room && !lobby.is_host && ((lobby.status === 'lobby' && lobby.joined) || lobby.is_waiting)
                ? {id: 'nc-unseat', label: 'Покинуть стол', hint: 'место освободится', icon: menuIcon('table'), onSelect: () => confirmLeave(lobby, 'seat')} : null,
            ctx.room && !owner ? {id: 'nc-leave', label: 'Покинуть комнату', hint: 'с подтверждением', icon: menuIcon('door'), danger: true, onSelect: () => confirmLeave(lobby, 'room')} : null,
        ];
    }
    function clockFor(lobby) {
        ctx.timer?.stop(); ctx.timer = null;
        if (!lobby.ends_at || !['night', 'day', 'voting'].includes(lobby.status)) return null;
        ctx.timer = kit.timer({endsAt: Number(lobby.ends_at), serverNow: Number(lobby.server_now), total: Number(lobby.phase_seconds) || PHASE_SECONDS[lobby.status],
            icon: {night: 'moon', day: 'sun', voting: 'scales'}[lobby.status], alive, onExpire: () => later(() => refresh(), 1500)});
        return ctx.timer;
    }
    function historyItems(lobby) {
        const items = [];
        for (const event of lobby.history || []) {
            const name = event.eliminated ? event.eliminated_name || seatName(lobby, event.eliminated) : null;
            const revealed = name && lobby.status === 'finished' ? lobby.players.find(player => player.seat === event.eliminated)?.role : null;
            const suffix = revealed ? [' — ', {cls: ROLES[revealed]?.cls, text: ROLES[revealed]?.title.toLowerCase()}] : [];
            if (event.type === 'started') items.push({icon: 'table', when: 'Начало дела', what: 'Роли розданы, город засыпает'});
            else if (event.type === 'night_result') items.push({icon: 'moon', when: `Ночь ${event.round} → утро`,
                what: name ? ['Ночью мафия вывела из игры: ', {b: name}, ...suffix] : event.saved ? 'Доктор спас цель мафии' : 'Ночь прошла без потерь'});
            else items.push({icon: 'scales', when: `День ${event.round} · голосование`,
                what: name ? ['Город вывел из игры: ', {b: name}, ...suffix] : 'Голоса разделились — никто не выбыл'});
        }
        return items;
    }
    const caseLog = lobby => {
        const items = historyItems(lobby);
        return items.length ? kit.caseLog(items, {note: lobby.status === 'finished' ? 'с ролями' : 'роли скрыты до конца'}) : null;
    };
    function badge(lobby, role, line) {
        const info = ROLES[role.role] || ROLES.citizen;
        return kit.roleBadge({title: info.you, line, icon: info.icon, faction: info.faction, action: {label: 'Показать', onClick: () => showOverlay('role')}});
    }
    function investigationLine(lobby, role) {
        const check = role.investigation;
        if (!check) return null;
        return [`проверка ночи ${check.round}: ${seatName(lobby, check.seat)} — `, {cls: check.is_mafia ? 'nc-role-mafia' : '', b: check.is_mafia ? 'мафия' : 'не мафия'}];
    }
    function chatPanel(lobby, role, {readOnly = false} = {}) {
        const talk = ctx.data.talk;
        if (!talk) return null;
        const byName = new Map(lobby.players.map(player => [player.name, player]));
        const feed = (talk.items || []).map(item => ({me: item.is_me, name: item.author, text: item.message, portrait: portraitOf(byName.get(item.author) || {seat: 'p1'})}));
        const messages = lobby.status === 'lobby' ? [{sys: 'Стол открыт', icon: 'table'}, ...feed]
            : [...feed, {sys: lobby.status === 'day' ? `День ${lobby.round} · обсуждение открыто` : lobby.status === 'voting' ? `День ${lobby.round} · голосование` : `Ночь ${lobby.round}`,
                icon: {day: 'sun', voting: 'scales'}[lobby.status] || 'moon'}];
        const out = role && role.alive === false;
        const writable = (typeof talk.can_post === 'boolean' ? talk.can_post : talk.enabled) && !readOnly && !out;
        return kit.chat({messages, composer: {key: `${tableKey()}`, enabled: writable,
            closed: out || (talk.enabled && talk.can_post === false) ? ['eye', 'Выбывшие читают обсуждение, но не пишут и не голосуют']
                : ['lock', lobby.status === 'night' ? 'Обсуждение откроется днём' : 'Обсуждение сейчас закрыто'],
            onSend: text => command('/discussion', {message: text}, 'Сообщение', null, {onAccepted: () => kit.drafts.set(tableKey(), '')})}});
    }

    /* --- room screens --- */
    function renderNoTable() {
        menu([rulesItem()]);
        frame({eyebrow: 'Ночной город · Комната', title: tableTitle(), scene: {slot: 'lobby', time: 'evening'}, main: [
            kit.scene({slot: 'lobby', time: 'evening', eyebrow: 'Комната', title: 'Стол ещё не накрыт',
                text: ctx.group ? 'Сядь за стол первым — остальные присоединятся из группы.' : 'Хозяин комнаты откроет стол, и здесь появятся места.'}),
        ], dock: ctx.group ? kit.dock({buttons: [kit.button('Сесть за стол', event => command('/lobby/join', {}, 'Место за столом', event.currentTarget), {kind: 'primary'})]}) : null});
    }
    function invitePanel() {
        if (ctx.room?.role !== 'owner') return null;
        const invite = createdInvites.get(ctx.room.id);
        const until = ctx.room.open && ctx.room.open_expires_at ? new Date(ctx.room.open_expires_at) : null;
        const openToggle = () => typeof ctx.room.open === 'boolean' ? kit.toggle({title: 'Открытая комната', on: ctx.room.open,
            text: until && !Number.isNaN(until.getTime())
                ? `Стол в «Открытых столах». Без активности уйдёт из списка в ${String(until.getHours()).padStart(2, '0')}:${String(until.getMinutes()).padStart(2, '0')}.`
                : 'Стол появится в «Открытых столах»: сесть сможет любой, пока партия не началась.', onChange: on => setOpen(on)}) : null;
        if (!invite) return kit.panel({icon: 'seal', title: 'Пригласить', count: '24 ч · до 10 входов'},
            kit.note('Создай приглашение: получишь код и ссылку, которые можно отправить друзьям.'),
            kit.stack(kit.button('Создать приглашение', event => issueInvite(event.currentTarget), {icon: 'envelope'})), openToggle());
        return kit.panel({icon: 'seal', title: 'Пригласить', count: '24 ч · до 10 входов'},
            kit.ticket({code: invite.short_code || invite.invite_code, onCopy: code => copyText(code, 'Код скопирован.')}),
            kit.stack(kit.button('Поделиться ссылкой', () => shareInvite(invite), {icon: 'envelope'})),
            kit.note(options.telegram?.() ? 'Ссылка откроет стол в Telegram. Код вводят в «Войти по приглашению».'
                : 'Ссылка откроет стол в браузере. Код вводят в «Войти по приглашению».'), openToggle());
    }
    async function issueInvite(button = null) {
        if (!ctx.room || ctx.room.role !== 'owner') return;
        if (button) button.disabled = true;
        try {
            const invite = await request(`/api/guest/rooms/${encodeURIComponent(ctx.room.id)}/invites`, {method: 'POST', body: {expires_in_seconds: 86400, max_uses: 10}});
            createdInvites.set(ctx.room.id, invite); ctx.notice = null;
        } catch (error) { ctx.notice = {text: error.message}; }
        if (alive()) { ctx.fingerprint = ''; render(); }
    }
    async function setOpen(on) {
        try { const room = await request(`/api/guest/rooms/${encodeURIComponent(ctx.room.id)}/open`, {method: 'POST', body: {open: on}, key: uuid()}); ctx.room = {...ctx.room, ...room, open: room?.open ?? on}; }
        catch (error) { ctx.notice = {text: error.message}; }
        if (alive()) render();
    }
    async function copyText(text, done) {
        try { await globalThis.navigator.clipboard.writeText(text); ctx.notice = {text: done, tone: 'warn', icon: 'check'}; }
        catch { ctx.notice = {text: `Скопируй вручную: ${text}`}; }
        render();
    }
    async function shareInvite(invite) {
        const tg = options.telegram?.();
        const text = `Садись за стол «${ctx.room.title || 'Ночной город'}» в Ночном городе.${invite.short_code ? ` Код: ${invite.short_code}` : ''}`;
        const url = (tg?.initData && invite.telegram_url) || invite.web_url || invite.telegram_url;
        if (tg?.initData && tg.openTelegramLink && url) {
            try { tg.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`); return; } catch { /* fall back */ }
        }
        if (globalThis.navigator?.share && url) {
            try { await globalThis.navigator.share({title: 'Ночной город', text, url}); return; } catch (error) { if (error?.name === 'AbortError') return; }
        }
        await copyText(url ? `${text}\n${url}` : text, 'Ссылка скопирована — отправь её друзьям.');
    }
    function confirmLeave(lobby, what = 'room') {
        ctx.notice = null;
        const seated = what === 'seat';
        const inGame = !seated && lobby?.joined && ['night', 'day', 'voting'].includes(lobby.status) && me(lobby)?.alive !== false;
        const leave = kit.button(seated ? 'Покинуть стол' : 'Покинуть комнату', async () => {
            leave.disabled = true;
            if (seated) { ctx.leaveConfirm = null; await command('/lobby/unseat', {}, 'Уход из-за стола', leave); return; }
            try {
                await request(`/api/guest/rooms/${encodeURIComponent(ctx.room.id)}/leave`, {method: 'POST', body: {membership_version: ctx.room.membership_version}});
                if (alive()) showEntry({text: gm('Ты вышел из комнаты.', 'Ты вышла из комнаты.', 'Комната покинута.') + ' Вернуться можно по новому приглашению.', icon: 'door'});
            } catch (error) { ctx.leaveConfirm = null; ctx.notice = {text: error.message}; render(); }
        }, {kind: 'danger'});
        ctx.leaveConfirm = kit.alert({icon: 'door', title: seated ? 'Покинуть стол?' : 'Покинуть комнату?',
            text: seated ? 'Место освободится. Сесть снова можно, пока партия не началась.'
                : inGame ? 'Идёт партия: твой герой выбудет из дела. Вернуться в комнату можно только по новому приглашению.'
                    : 'Вернуться в комнату можно только по новому приглашению.',
            actions: [kit.button('Остаться', () => { ctx.leaveConfirm = null; render(); }), leave]});
        render();
    }
    /* ---------- the story (world) of the room: the host chooses before the night, everybody sees it ---------- */
    const canPickWorld = lobby => Boolean(ctx.room && lobby?.is_host && lobby.status === 'lobby');
    /** Name of a world from the index or from the applied pack (null when neither is known). */
    function worldTitle(id) { return kit.worldEntry(id)?.title || (kit.pack?.id === id ? kit.pack.title : null) || null; }
    function storyPanel(lobby) {
        if (!ctx.room) return null;                      // a Telegram group table plays the default story
        const id = lobby.world || DEFAULT_WORLD;
        const entry = kit.worldEntry(id), pack = kit.pack?.id === id ? kit.pack : null;
        const title = entry?.title || pack?.title;
        if (!title) return null;                         // neither the index nor the pack is known: no panel, the table still works
        const thumb = entry ? kit.thumbUrl(entry) : packUrl(pack.thumb);
        const era = entry?.era ?? pack?.era ?? '';
        const change = canPickWorld(lobby) ? kit.button('Сменить', () => openWorldPicker(), {kind: 'text', compact: true, crumb: 'nc-world'}) : null;
        const copy = put(el('div'), put(el('strong'), title, kit.worldAge(id, lobby.world_age) >= 16 ? ageBadge(kit.worldAge(id, lobby.world_age)) : null), el('span', null, [era, change ? null : lobby.status === 'lobby' ? 'выбирает ведущий' : null].filter(Boolean).join(' · ')));
        const node = put(el('div', `nc-story${thumb ? '' : ' nothumb'}`), thumb ? Object.assign(el('img'), {src: thumb, alt: ''}) : null, copy, change);
        return kit.panel({icon: 'story', title: 'Сюжет'}, node);
    }
    function loadWorldIndex() {
        ctx.worldIndex = undefined;
        kit.worldIndex().then(index => { if (!alive()) return; ctx.worldIndex = index; if (ctx.overlay === 'world') render(); });
    }
    function openWorldPicker() {
        ctx.worldPick = null; ctx.worldScroll = true;      // the first render brings the chosen story into view
        showOverlay('world');
        loadWorldIndex();
    }
    function renderWorldPicker(lobby) {
        const now = lobby.world || DEFAULT_WORLD, picked = ctx.worldPick || now, index = ctx.worldIndex;
        let content;
        if (index === undefined) content = kit.note('Загружаем сюжеты…', 'nc-note nc-loading');
        else if (!index) content = [kit.note('Список сюжетов не загрузился. Стол работает как раньше.', 'nc-note error'), kit.row(kit.button('Повторить', () => { loadWorldIndex(); render(); }, {compact: true}))];
        else content = put(el('div', 'nc-worlds'), index.worlds.map(world => {
            const on = world.id === picked, current = world.id === now;
            // The choice reads without colour: a thick rim, a filled tick and the word «выбран» / «сейчас за столом».
            const button = attr(el('button', `nc-world${current ? ' current' : ''}`), {'aria-pressed': String(on)}); button.type = 'button';
            button.dataset.world = world.id;
            const thumb = kit.thumbUrl(world);
            const state = on ? el('span', 'w-state', current ? 'сейчас' : 'выбран') : current ? el('span', 'w-state now', 'сейчас') : null;
            put(button, put(el('span', 'w-pic'), thumb ? Object.assign(el('img'), {src: thumb, alt: ''}) : null,
                world.default ? el('span', 'w-tag', 'тестовая партия') : null, on ? withClass(kit.icon('check'), 'tick') : null),
                put(el('span', 'w-copy'), put(el('span', 'w-name'), world.title, kit.worldAge(world.id, world.age) >= 16 ? ageBadge(kit.worldAge(world.id, world.age)) : null),
                    world.era ? el('span', 'w-era', world.era) : null, state));
            if (world.accent) setVar(button, '--w-accent', world.accent);
            button.addEventListener('click', () => { ctx.worldPick = world.id; render(); });
            return button;
        }));
        const pickedTitle = index ? index.worlds.find(world => world.id === picked)?.title : null;
        const adult = kit.worldAge(picked, index?.worlds.find(world => world.id === picked)?.age) >= 18;
        const choose = button => command('/world', {world: picked, expected_revision: lobby.revision, ...(adult ? {age_ok: true} : {})}, 'Смена сюжета', button,
            {room: true, onAccepted: () => { ctx.room = {...ctx.room, world: picked}; ctx.worldPick = null; dropOverlay(); }});
        const confirm = kit.button(pickedTitle && picked !== now ? `Выбрать: ${pickedTitle}` : 'Выбрать', event => { if (adult && !age18Known()) askAge18(() => choose(null), picked); else choose(event.currentTarget); },
            {kind: 'primary', disabled: !index || picked === now || ctx.net});
        frame({eyebrow: 'Ночной город · Сюжет', title: tableTitle(), scene: {slot: 'cover'}, net: ctx.net, main: [
            put(el('div', 'nc-span nc-col'), kit.panel({icon: 'story', title: 'Сюжет комнаты', count: index ? `${index.worlds.length} миров` : ''},
                kit.note('Сюжет меняет вид стола: места, портреты, карты и цвет. Правила партии те же. Менять можно до начала партии.'), content))],
            dock: kit.dock({layout: 'row', hint: picked === now ? 'Выбери другой сюжет — его увидят все за столом' : 'Сюжет увидят все за столом', buttons: [kit.button('Назад', closeOverlay), confirm]})});
        if (index && ctx.worldScroll) {
            ctx.worldScroll = false;
            const chosen = host.querySelector?.(`.nc-world[data-world="${picked}"]`);
            const dockTop = host.querySelector?.('.nc-dock')?.getBoundingClientRect?.().top ?? globalThis.innerHeight;
            try { if (chosen && chosen.getBoundingClientRect().bottom > dockTop - 8) chosen.scrollIntoView({block: 'center'}); } catch { /* old engines */ }
        }
    }
    function lobbySeats(lobby) {
        const remover = ctx.room && lobby.is_host && lobby.status === 'lobby';
        const removeButton = (ref, name) => kit.button('Убрать', () => confirmRemove(lobby, ref, name), {kind: 'danger', compact: true});
        const seats = lobby.players.map(player => ({name: player.name, portrait: portraitOf(player), me: player.is_me,
            sub: [player.is_me ? 'ты' : null, player.is_me && lobby.is_host ? 'ведущий' : null].filter(Boolean).join(' · '),
            end: [player.ready ? kit.tag('готов', {tone: 'ok', icon: 'check'}) : kit.tag('думает', {icon: 'hourglass'}),
                player.is_me && ctx.room && lobby.status === 'lobby' ? kit.button('Портрет', () => showOverlay('portrait'), {kind: 'text', compact: true}) : null,
                remover && !player.is_me ? removeButton(player.seat, player.name) : null]}));
        const waiting = (lobby.waiting || []).map((item, index) => ({name: item.name, portrait: item.portrait ?? kit.PORTRAITS - (index % kit.PORTRAITS), out: false,
            sub: item.is_me ? 'ты · ждёшь следующую партию' : 'ждёт следующую партию',
            end: [kit.tag('в очереди', {icon: 'hourglass'}), ctx.room && lobby.is_host && !item.is_me ? removeButton(item.ref, item.name) : null]}));
        return kit.seats([...seats, ...waiting]);
    }
    function confirmRemove(lobby, ref, name) {
        ctx.leaveConfirm = kit.alert({icon: 'door', title: `Убрать ${name} из-за стола?`, text: 'Вернуться в эту комнату можно будет только по новому приглашению.',
            actions: [kit.button('Оставить', () => { ctx.leaveConfirm = null; render(); }),
                kit.button('Убрать', event => { ctx.leaveConfirm = null; command('/lobby/remove', {target: ref, expected_revision: lobby.revision}, 'Убрать игрока', event.currentTarget); }, {kind: 'danger'})]});
        render();
    }
    function renderPortrait(lobby) {
        const mine = me(lobby);
        const taken = lobby.players.filter(player => !player.is_me).map(player => player.portrait).filter(Number.isFinite);
        frame({eyebrow: 'Ночной город · Комната', title: tableTitle(), scene: {slot: 'lobby', time: 'evening'}, net: ctx.net, main: [
            put(el('div', 'nc-span nc-col'), kit.panel({icon: 'people', title: 'Твой портрет за столом', count: 'видят все'},
                kit.note('Портрет — только лицо за столом: роль он не выдаёт. Занятые другими недоступны.'),
                kit.portraits({count: Math.min(Number(lobby.portrait_count) || kit.PORTRAITS, kit.PORTRAITS), selected: mine?.portrait ?? null, taken, disabled: ctx.net,
                    onSelect: n => command('/lobby/portrait', {expected_revision: lobby.revision, portrait: n}, 'Портрет')})))],
            dock: kit.dock({buttons: [kit.button('Готово', closeOverlay, {kind: 'primary'})]})});
    }
    function renderLobby(lobby) {
        const ready = Number.isFinite(lobby.ready_count) ? lobby.ready_count : lobby.players.filter(player => player.ready).length, total = lobby.players.length;
        const mine = me(lobby), joined = lobby.joined, playing = lobby.status !== 'lobby';
        const min = Number(lobby.min_players) || 4, allReady = lobby.start_requires_all_ready !== false;
        const title = playing ? 'Партия уже идёт' : lobby.is_host ? `Готовы ${ready} из ${total}` : 'Ждём готовности';
        const startRule = allReady ? `Начать можно, когда за столом от ${min} и все отметили готовность.`
            : `Начать можно, когда готовы хотя бы ${min}. Кто не успел — сядет в следующую партию.`;
        const text = playing ? (lobby.is_waiting ? 'Ты в очереди: сядешь за стол в следующей партии.' : 'Сесть можно, когда начнётся следующая партия.')
            : lobby.is_host ? (lobby.can_start ? (ready < total ? `Готовых хватает — можно начинать. Не готовые (${total - ready}) сыграют в следующей партии.` : 'Все готовы — можно начинать ночь.') : startRule)
                : joined ? 'Отметь готовность, когда сможешь играть ~20 минут. Начнёт ведущий.' : 'Сядь за стол, чтобы играть в следующей партии.';
        const left = put(el('div', 'nc-col'), storyPanel(lobby), invitePanel(),
            kit.panel({icon: 'people', title: 'За столом', count: `${total} из 12 · готовы ${ready}`}, lobbySeats(lobby)));
        const right = put(el('div', 'nc-col'), joined ? chatPanel(lobby, null) : null);
        let dock;
        if (playing) dock = !ctx.room || joined ? null
            : lobby.is_waiting ? kit.dock({hint: 'Ты в очереди на следующую партию', buttons: [kit.button('Не ждать', event => command('/lobby/unseat', {}, 'Выход из очереди', event.currentTarget))]})
                : kit.dock({hint: 'Сядешь за стол, когда начнётся новая партия', buttons: [kit.button('Ждать следующую', event => command('/lobby/wait', {}, 'Место в следующей партии', event.currentTarget), {kind: 'primary', icon: 'hourglass'})]});
        else if (!joined) dock = kit.dock({buttons: [kit.button('Сесть за стол', event => command('/lobby/join', {}, 'Место за столом', event.currentTarget), {kind: 'primary', icon: 'table'})]});
        else {
            const readyButton = kit.button(mine?.ready ? gm('Я не готов', 'Я не готова', 'Снять готовность') : gm('Я готов', 'Я готова', 'Отметить готовность'),
                event => command('/lobby/ready', {ready: !mine?.ready, expected_revision: lobby.revision}, 'Готовность', event.currentTarget),
                {kind: lobby.is_host || mine?.ready ? 'secondary' : 'primary', icon: mine?.ready ? null : 'check'});
            dock = lobby.is_host
                ? kit.dock({layout: 'row', hint: lobby.can_start ? 'Роли раздаст приложение — каждому тайно'
                    : !mine?.ready ? 'Отметь и свою готовность — без неё начать нельзя' : `Нужно от ${min} готовых игроков`,
                    buttons: [readyButton, kit.button('Начать ночь', event => command('/lobby/start', {expected_revision: lobby.revision}, 'Начало ночи', event.currentTarget), {kind: 'primary', disabled: !lobby.can_start})]})
                : kit.dock({hint: ctx.room?.role === 'owner' ? '' : 'Начнёт ведущий, когда все будут готовы', buttons: [readyButton]});
        }
        frame({eyebrow: 'Ночной город · Комната', title: tableTitle(), scene: {slot: 'lobby', time: 'evening'}, net: ctx.net, dock, main: [
            kit.scene({slot: 'lobby', time: 'evening', eyebrow: playing ? 'Идёт партия' : 'Собираем стол', title, text,
                body: kit.track({total: 12, taken: total, ready, label: `${total} из 12 мест занято, ${ready} готовы`})}),
            left, right]});
    }
    function renderRoleBack(lobby) {
        menu(tableMenu(lobby));
        const turn = () => { seenRole.add(`${tableKey()}:${lobby.phase_revision}`); showOverlay('role'); };
        frame({eyebrow: `Ночной город · Ночь ${lobby.round}`, title: tableTitle(), clock: clockFor(lobby)?.clock, scene: {slot: 'night', time: 'night'}, net: ctx.net,
            main: [put(el('div', 'nc-span nc-col nc-reveal'), el('span', 'nc-eyebrow', `Роли розданы · ночь ${lobby.round}`), kit.roleCard({face: false, onOpen: turn}),
                kit.secret('Роль увидишь только ты. Убедись, что экран никто не видит.'))],
            dock: kit.dock({buttons: [kit.button('Открыть свою роль', turn, {kind: 'primary', crumb: 'nc-role-open'})]})});
    }
    function renderRoleFace(role) {
        const info = ROLES[role.role] || ROLES.citizen, lobby = ctx.data.lobby;
        seenRole.add(`${tableKey()}:${lobby.phase_revision}`);
        const team = role.teammates?.length ? kit.note(['Напарники: ', ...role.teammates.flatMap((mate, i) => [i ? ', ' : '', {b: mate.name}])]) : null;
        frame({eyebrow: `Ночной город · ${lobby.status === 'night' ? 'Ночь' : 'День'} ${lobby.round || 1}`, title: tableTitle(), clock: clockFor(lobby)?.clock,
            scene: {slot: 'night', time: 'night'}, net: ctx.net,
            main: [put(el('div', 'nc-span nc-role-pair'), kit.roleCard({face: true, title: info.title, side: info.side, faction: info.faction, onClose: closeOverlay}),
                kit.panel({}, kit.note(info.about, 'nc-lead'), team, kit.abilities(info.rows.map(([icon, term, text]) => ({icon, term, text}))), kit.secret('Не показывай экран соседям')))],
            dock: kit.dock({hint: `Карточку можно открыть снова: «${info.you} · Показать»`, buttons: [kit.button(lobby.status === 'night' ? 'Понятно, к ночи' : 'Понятно', closeOverlay, {kind: 'primary'})]})});
    }
    function renderRules() {
        frame({eyebrow: 'Ночной город · Правила', title: 'Правила дела', scene: {slot: 'vote'}, main: [
            kit.scene({slot: 'vote', size: 'short', eyebrow: 'Правила', title: 'Как идёт дело', text: 'Короткая партия: ночь, день, голосование — пока одна из сторон не победит.'}),
            put(el('div', 'nc-col'), kit.panel({icon: 'papers', title: 'Ход партии'}, kit.abilities(RULES.map(([icon, term, text]) => ({icon, term, text}))))),
            put(el('div', 'nc-col'), kit.panel({icon: 'seal', title: 'Роли'}, kit.abilities(Object.values(ROLES).map(info => ({icon: info.icon, term: info.title, text: info.about}))))),
        ], dock: kit.dock({buttons: [kit.button('Понятно', closeOverlay, {kind: 'primary'})]})});
    }
    function targetPicker(lobby, role, {verb, voting = false}) {
        const pickKey = `${tableKey()}:${lobby.phase_revision}`;
        const done = voting ? role.voted : role.acted;
        const selected = pickedTargets.get(pickKey) || null;
        const check = role.investigation;
        const items = (role.targets || []).map(target => {
            const player = lobby.players.find(item => item.seat === target.seat) || {seat: target.seat};
            const sub = voting && typeof player.voted === 'boolean' ? (player.voted ? 'голос сдан' : 'думает')
                : check && check.seat === target.seat ? {cls: check.is_mafia ? 'mark-team' : 'mark-check', text: check.is_mafia ? 'мафия' : 'не мафия'} : null;
            return {id: target.seat, name: target.name, portrait: portraitOf(player), sub};
        });
        const picker = kit.picker({items, selected, disabled: done || ctx.net, label: verb, onSelect: seat => { if (seat) pickedTargets.set(pickKey, seat); else pickedTargets.delete(pickKey); render(); }});
        const chosen = items.find(item => item.id === selected);
        const confirm = done ? null : kit.button(chosen ? `${verb.button}: ${chosen.name}` : verb.empty, async event => {
            await command(voting ? '/vote' : '/action', {target: chosen.id, expected_revision: lobby.phase_revision}, voting ? `Голос против: ${chosen.name}` : 'Ночной ход',
                event.currentTarget, {onAccepted: () => { confirmedTargets.set(pickKey, chosen.name); pickedTargets.delete(pickKey); }});
        }, {kind: 'primary', disabled: !chosen || ctx.net});
        if (ctx.net && !done) confirm.replaceChildren(textNode('Ждём связь…'));
        return {picker, confirm};
    }
    function hostAdvance(lobby, label, hint) {
        return lobby.is_host && lobby.can_advance ? {button: kit.button(label, event => command('/advance', {expected_revision: lobby.revision}, label, event.currentTarget), {icon: 'scales'}), hint} : null;
    }
    function lostCommandAlert() {
        const lost = pendingCommands.get(tableKey());
        return lost && ctx.net ? kit.alert({icon: 'hourglass', title: `${lost.label} — ответ не дошёл`,
            text: 'Связь пропала во время отправки. Когда она вернётся, проверим — второй раз не засчитается.',
            actions: [kit.button('Проверить сейчас', () => refresh(true), {compact: true})]}) : null;
    }
    function renderNight(lobby, role) {
        const timer = clockFor(lobby), info = ROLES[role?.role] || ROLES.citizen;
        const key = `${tableKey()}:${lobby.phase_revision}`, chosen = confirmedTargets.get(key);
        const steps = kit.steps(PHASES, 'night');
        let main, dock = null;
        if (role?.role === 'citizen' || !role) {
            main = [kit.scene({slot: 'night', time: 'night', eyebrow: `Ночь ${lobby.round}`, title: 'Город спит', text: 'У мирных ночью хода нет. Утром — обсуждение и голосование.', steps, bar: timer?.bar}),
                put(el('div', 'nc-col'), role ? badge(lobby, role, 'твоё оружие — обсуждение и голос') : null,
                    kit.panel({icon: 'eye', title: 'Пока город спит'}, kit.note('Вспомни, кто вчера голосовал против кого и кто молчал. Экран сам перейдёт к утру.', 'nc-muted'), kit.closed('lock', 'Обсуждение откроется днём')))];
        } else if (role.acted) {
            const line = {mafia: 'цель — по большинству голосов мафии', detective: 'проверяешь одного игрока за ночь', doctor: 'защищаешь одного игрока за ночь'}[role.role];
            const done = chosen ? {mafia: `Твой выбор этой ночью — ${chosen}`, detective: `Этой ночью ты проверяешь: ${chosen}`, doctor: `Этой ночью ты защищаешь: ${chosen}`}[role.role] : 'Твой ход принят';
            const tally = Number.isFinite(lobby.night_acted) && Number.isFinite(lobby.night_needed)
                ? kit.panel({icon: 'hourglass', title: 'Ночные роли', count: `сделали ход ${lobby.night_acted} из ${lobby.night_needed}`},
                    kit.track({total: lobby.night_needed, taken: lobby.night_needed, ready: lobby.night_acted}), kit.note('Кто именно ещё думает — тайна.')) : null;
            main = [kit.scene({slot: 'night', time: 'night', eyebrow: `Ночь ${lobby.round}`, title: 'Твой ход сделан',
                    text: timer ? `Утро наступит, когда все ночные роли сделают ход, или через ${clockText(timer.remaining())}.` : 'Утро наступит, когда все ночные роли сделают ход.', steps, bar: timer?.bar}),
                put(el('div', 'nc-col'), badge(lobby, role, line), kit.alert({icon: 'check', title: done, text: role.role === 'detective' ? 'Ответ придёт утром — только тебе.' : 'Выбор не меняется до утра.'}), tally)];
        } else {
            const verbs = {mafia: {title: 'Кого убрать из игры этой ночью?', button: 'Выбрать', empty: 'Выбери цель'},
                detective: {title: 'Кого проверить?', button: 'Проверить', empty: 'Выбери, кого проверить'},
                doctor: {title: 'Кого защитить этой ночью?', button: 'Защитить', empty: 'Выбери, кого защитить'}}[role.role];
            const {picker, confirm} = targetPicker(lobby, role, {verb: verbs});
            const team = role.role === 'mafia' && role.teammates?.length ? put(el('div', 'nc-team'), kit.avatar({portrait: portraitOf(lobby.players.find(p => p.seat === role.teammates[0].seat) || {}), size: 'sm'}),
                rich([role.teammates.length > 1 ? 'Напарники: ' : 'Напарник: ', ...role.teammates.flatMap((mate, i) => [i ? ', ' : '', {b: mate.name}]),
                    ...(role.teammates[0].target_name ? [' · выбрал ', {b: role.teammates[0].target_name}] : [])])) : null;
            const lead = {mafia: 'Мафия выбирает цель. Доктор и детектив тоже делают ход.', detective: 'Выбери, кого проверить. Ответ придёт утром — только тебе.', doctor: 'Выбери, кого защитить. Если мафия выберет его, он останется в игре.'}[role.role];
            const check = role.role === 'detective' && role.investigation ? kit.alert({icon: 'lens',
                title: [`Проверка ночи ${role.investigation.round}: ${seatName(lobby, role.investigation.seat)} — `, {b: role.investigation.is_mafia ? 'мафия' : 'не мафия'}], text: 'Это знаешь только ты.'}) : null;
            main = [kit.scene({slot: 'night', time: 'night', size: 'short', eyebrow: `Ночь ${lobby.round}`, title: 'Город спит', text: lead, steps, bar: timer?.bar}),
                put(el('div', 'nc-col'), badge(lobby, role, {mafia: 'цель — по большинству голосов мафии', detective: 'проверяешь одного игрока за ночь', doctor: 'защищаешь одного игрока за ночь'}[role.role]),
                    team, check, lostCommandAlert(), kit.panel({}, el('h2', 'nc-h3', verbs.title), picker,
                        role.role === 'mafia' ? kit.note('Напарников в списке нет. Выбывших — тоже.') : null))];
            dock = kit.dock({hint: 'После подтверждения выбор не меняется', buttons: [confirm]});
        }
        const advance = hostAdvance(lobby, 'Объявить утро', 'Все ночные роли сделали ход');
        if (advance && !dock) dock = kit.dock({hint: advance.hint, buttons: [advance.button]});
        main.push(put(el('div', 'nc-col'), caseLog(lobby)));
        frame({eyebrow: `Ночной город · Ночь ${lobby.round}`, title: tableTitle(), clock: timer?.clock, scene: {slot: 'night', time: 'night'}, net: ctx.net, main, dock});
    }
    function nightHeadline(lobby) {
        const last = [...(lobby.history || [])].reverse().find(event => event.type === 'night_result' && event.round === lobby.round);
        if (!last) return {title: 'Город просыпается', text: 'Обсудите, кого подозреваете.'};
        if (last.eliminated) return {title: `${last.eliminated_name || seatName(lobby, last.eliminated)} выбывает`, text: 'Роль откроется в конце дела. Обсудите, кто мог это сделать.'};
        return last.saved ? {title: 'Все живы', text: 'Доктор спас цель мафии. Обсудите, кто на кого охотился.'} : {title: 'Ночь прошла тихо', text: 'Никто не выбыл. Обсудите, кого подозреваете.'};
    }
    function seatsAtTable(lobby) {
        const alive = lobby.players.filter(player => player.alive !== false), out = lobby.players.filter(player => player.alive === false);
        const history = lobby.history || [];
        const when = seat => { const event = history.find(item => item.eliminated === seat); return event ? (event.type === 'night_result' ? `вне игры · ночь ${event.round}` : `вне игры · голосование дня ${event.round}`) : 'вне игры'; };
        return kit.panel({icon: 'people', title: 'За столом', count: `в игре ${alive.length} из ${lobby.players.length}`},
            kit.seats([...alive.map(player => ({name: player.name, portrait: portraitOf(player), me: player.is_me, sub: player.is_me ? 'ты' : ''})),
                ...out.map(player => ({name: player.name, portrait: portraitOf(player), out: true, sub: when(player.seat)}))]));
    }
    function renderDay(lobby, role) {
        const timer = clockFor(lobby), head = nightHeadline(lobby);
        const advance = hostAdvance(lobby, 'Открыть голосование сейчас', 'Ты ведущий: можно не ждать, если все договорились');
        frame({eyebrow: `Ночной город · День ${lobby.round}`, title: tableTitle(), clock: timer?.clock, scene: {slot: 'day', time: 'morning'}, net: ctx.net,
            main: [kit.scene({slot: 'day', time: 'morning', eyebrow: `Утро после ночи ${lobby.round}`, title: head.title, text: head.text, steps: kit.steps(PHASES, 'day'), bar: timer?.bar}),
                put(el('div', 'nc-col'), role ? badge(lobby, role, investigationLine(lobby, role) || {mafia: 'не выдай себя', doctor: 'защищаешь одного игрока за ночь', citizen: 'твоё оружие — обсуждение и голос'}[role.role] || '') : null,
                    lostCommandAlert(), chatPanel(lobby, role)),
                put(el('div', 'nc-col'), seatsAtTable(lobby), caseLog(lobby))],
            dock: advance ? kit.dock({hint: advance.hint, buttons: [advance.button]}) : null});
    }
    function renderVote(lobby, role) {
        const timer = clockFor(lobby);
        const {picker, confirm} = targetPicker(lobby, role || {targets: []}, {verb: {button: 'Голосовать против', empty: 'Выбери, против кого'}, voting: true});
        const cast = Number.isFinite(lobby.votes_cast) ? `сдали ${lobby.votes_cast} из ${lobby.votes_needed}` : '';
        const advance = hostAdvance(lobby, 'Подвести итоги', 'Все голоса сданы');
        const voted = role?.voted;
        const chosen = confirmedTargets.get(`${tableKey()}:${lobby.phase_revision}`);
        frame({eyebrow: `Ночной город · День ${lobby.round}`, title: tableTitle(), clock: timer?.clock, scene: {slot: 'vote'}, net: ctx.net,
            main: [kit.scene({slot: 'vote', size: 'short', eyebrow: `Голосование · день ${lobby.round}`, title: 'Кого вывести из игры?',
                    text: 'Голос тайный. Выбывает тот, у кого больше всех голосов; при ничьей никто.', steps: kit.steps(PHASES, 'voting'), bar: timer?.bar}),
                put(el('div', 'nc-col'), lostCommandAlert(), voted ? kit.alert({icon: 'check', title: chosen ? `Твой голос — против: ${chosen}` : 'Голос принят', text: 'Ждём остальных. Голос нельзя изменить.'}) : null,
                    kit.panel({icon: 'scales', title: 'Твой голос', count: cast}, picker, kit.note('Видно только, сдан ли голос, — не за кого.'))),
                put(el('div', 'nc-col'), caseLog(lobby))],
            dock: !voted && confirm ? kit.dock({hint: 'Голос нельзя изменить', buttons: [confirm]}) : advance ? kit.dock({hint: advance.hint, buttons: [advance.button]}) : null});
    }
    function renderOut(lobby, role) {
        const timer = clockFor(lobby), info = ROLES[role.role] || ROLES.citizen;
        const event = (lobby.history || []).find(item => item.eliminated === role.seat);
        const how = event ? (event.type === 'night_result' ? `Мафия выбрала тебя ночью ${event.round}.` : `Город вывел тебя днём ${event.round}.`) : '';
        frame({eyebrow: `Ночной город · ${lobby.status === 'night' ? 'Ночь' : 'День'} ${lobby.round}`, title: tableTitle(), clock: timer?.clock, scene: {slot: 'out', time: 'evening'}, net: ctx.net,
            main: [kit.scene({slot: 'out', time: 'evening', eyebrow: 'Ты вне игры', title: 'Смотришь партию',
                    text: `${how} Можно следить за ходом дела до финала — роли откроются всем в конце.`.trim(), steps: kit.steps(PHASES, lobby.status), bar: timer?.bar}),
                put(el('div', 'nc-col'), kit.roleBadge({title: info.you, line: 'вне игры · для других роль пока тайна', icon: info.icon, faction: info.faction}), chatPanel(lobby, role, {readOnly: true})),
                put(el('div', 'nc-col'), seatsAtTable(lobby), caseLog(lobby))]});
    }
    function renderFinal(lobby, role) {
        ctx.timer?.stop();
        const town = lobby.winner === 'citizens';
        const abandoned = lobby.abandoned === true;
        const history = lobby.history || [];
        const fate = player => { const event = history.find(item => item.eliminated === player.seat);
            return event ? (event.type === 'night_result' ? `вне игры · ночь ${event.round}` : `вне игры · голосование дня ${event.round}`) : 'в игре до конца'; };
        const ordered = [...lobby.players.filter(player => player.role === 'mafia'), ...lobby.players.filter(player => player.role !== 'mafia')];
        const seats = ordered.map(player => {
            const info = ROLES[player.role] || null;
            return {name: player.name, portrait: portraitOf(player), me: player.is_me, out: player.alive === false,
                sub: [player.is_me ? 'ты' : null, fate(player)].filter(Boolean).join(' · '),
                end: info ? [put(el('span', `nc-role-chip ${info.cls}`), kit.icon(info.icon), info.title)] : []};
        });
        const exit = kit.button('Выйти', () => showEntry(), {icon: 'door'});
        const again = lobby.is_host ? kit.button('Сыграть ещё', event => command('/restart', {expected_revision: lobby.revision}, 'Новая партия', event.currentTarget), {kind: 'primary', icon: 'repeat'}) : null;
        frame({eyebrow: 'Ночной город · Дело закрыто', title: tableTitle(), scene: {slot: 'finale'}, net: ctx.net,
            main: [kit.scene({slot: 'finale', size: 'tall', eyebrow: `Дело закрыто · ${lobby.round || 1} дн.`, title: abandoned ? 'Стол опустел' : town ? 'Город победил' : 'Мафия взяла город',
                    text: abandoned ? 'Несколько раундов подряд никто не играл, партия закрыта без победителя.' : town ? 'Вся мафия выведена из игры.' : 'Мафии за столом стало не меньше, чем мирных.'}),
                put(el('div', 'nc-col'), role ? kit.roleBadge({title: (ROLES[role.role] || ROLES.citizen).you, line: abandoned ? 'партия закрыта без победителя' : (town ? role.role !== 'mafia' : role.role === 'mafia') ? 'твоя сторона победила' : 'твоя сторона проиграла',
                    icon: (ROLES[role.role] || ROLES.citizen).icon, faction: (ROLES[role.role] || ROLES.citizen).faction}) : null,
                    kit.panel({icon: 'seal', title: 'Кто был кем', count: 'роли открыты'}, kit.seats(seats))),
                put(el('div', 'nc-col'), caseLog(lobby))],
            dock: kit.dock({layout: 'row', hint: lobby.is_host ? 'Новая партия тем же столом: роли раздадут заново' : 'Новую партию начинает ведущий', buttons: [exit, again].filter(Boolean)})});
    }

    launch(options.target);
    return {kit, refresh: () => refresh(true), showEntry};
}

const NightCity = {kit, open, close() {}, parseLaunch, parseInvite};
window.NightCity = NightCity;
})();
