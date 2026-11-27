'use strict';
// «Ночной город»: shell and world packs (slots, fallback chains, palette, failures), the role card gestures, the 16+ mark.
// The kit runs in a vm with a small DOM double and a fake fetch; no browser.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {runInNewContext} = require('node:vm');

const root = path.resolve(__dirname, '..', '..');
const SOURCE = fs.readFileSync(path.join(root, 'web/mini_client/night-city-ui.js'), 'utf8');
const CSS = fs.readFileSync(path.join(root, 'web/mini_client/night-city.css'), 'utf8');
const DIR = path.join(root, 'web/mini_client/night');
// The built packs live outside git (MQB-012: web/mini_client/night/ is in .git/info/exclude),
// so a clean checkout such as CI cannot check them. Tests that read them skip there, by name.
const SHIPPED = fs.existsSync(path.join(DIR, 'worlds', 'index.json')) ? {} : {skip: 'web/mini_client/night/ is not built here (outside git)'};

class Node {
    constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.events = {}; this.style = {props: {}, setProperty(k, v) { this.props[k] = v; }, removeProperty(k) { delete this.props[k]; }};
        this.className = ''; this.classList = {add: (...names) => { for (const name of names) if (!this.className.split(' ').includes(name)) this.className = (this.className + ' ' + name).trim(); }}; this.text = ''; }
    append(...nodes) { this.children.push(...nodes); }
    setAttribute(key, value) { this.attrs[key] = String(value); }
    getAttribute(key) { return this.attrs[key]; }
    addEventListener(type, handler) { (this.events[type] ||= []).push(handler); }
    fire(type, event = {}) { for (const handler of this.events[type] || []) handler({preventDefault() { this.prevented = true; }, ...event}); }
    set textContent(value) { this.text = String(value); this.children = []; }
    get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
}
const find = (node, test) => { if (test(node)) return node; for (const child of node.children || []) { const hit = find(child, test); if (hit) return hit; } return null; };

function load({files = {}, fail = new Set()} = {}) {
    const requests = [];
    const doc = {documentElement: new Node('html'), createElement: tag => new Node(tag), createTextNode: text => Object.assign(new Node('#text'), {text: String(text)})};
    const fetch = async url => {
        const clean = String(url).split('?')[0];
        requests.push(String(url));
        if (fail.has(clean) || !(clean in files)) return {ok: false, status: 404, json: async () => ({})};
        return {ok: true, status: 200, json: async () => files[clean]};
    };
    const scope = {window: {}, document: doc, URL, fetch, AbortController, Date, setTimeout, clearTimeout};
    runInNewContext(SOURCE, scope);
    return {kit: scope.window.NightCity.kit, doc, requests};
}
const readJson = file => JSON.parse(fs.readFileSync(path.join(DIR, file), 'utf8'));
const realFiles = () => {
    const files = {'/app/night/worlds/index.json': readJson('worlds/index.json'), '/app/night/shell/shell.json': readJson('shell/shell.json')};
    for (const world of files['/app/night/worlds/index.json'].worlds) files[`/app/night/worlds/${world.id}/pack.json`] = readJson(`worlds/${world.id}/pack.json`);
    return files;
};

test('a world pack gives scenes by slot and time, portraits, emblems, frames and the palette; the shell has none of them', SHIPPED, async () => {
    const {kit, doc} = load({files: realFiles()});
    assert.equal(kit.world, null);
    assert.equal(kit.sceneUrl({slot: 'lobby', time: 'evening'}), '/app/night/shell/skyline.svg', 'no pack: the shell scene');
    assert.equal(kit.avatar({portrait: 3}).children[0].className.includes('ph'), true, 'no pack: neutral silhouette, no art');
    assert.equal(kit.art('card_back_role'), '');
    const pack = await kit.loadPack('neon_city');
    assert.equal(pack.id, 'neon_city');
    kit.useWorld(pack);
    assert.equal(kit.world, 'neon_city');
    assert.equal(doc.documentElement.dataset.ncWorld, 'neon_city');
    assert.equal(doc.documentElement.style.props['--nc-accent'], pack.palette.accent);
    assert.equal(doc.documentElement.style.props['--nc-edge-hc'], pack.palette.contrast.edge);
    assert.ok(!('--nc-display' in doc.documentElement.style.props), 'font.display = null: the shell font');
    for (const [slot, time] of [['lobby', 'evening'], ['night', 'night'], ['day', 'morning'], ['vote'], ['finale'], ['out', 'evening']]) {
        const url = kit.sceneUrl({slot, time});
        assert.match(url, /^\/app\/night\/worlds\/neon_city\/scene_[a-z_]+\.webp\?v=[0-9a-f]+$/, slot);
    }
    assert.equal(kit.PORTRAITS, 17);
    assert.match(kit.portraitUrl(5), /\/neon_city\/portrait_05\.webp/);
    assert.match(kit.art('emblem_shadow'), /emblem_shadow\.webp/);
    assert.match(kit.art('frame_hero'), /frame_hero\.webp/);
    // the shell again: palette and world are gone
    kit.useWorld(null);
    assert.equal(kit.world, null);
    assert.ok(!('--nc-accent' in doc.documentElement.style.props) && !doc.documentElement.dataset.ncWorld);
});

test('missing slots borrow the neighbour (vote → day → lobby, out → night → lobby, finale → cover → title), then the shell scene', SHIPPED, async () => {
    const pack = JSON.parse(JSON.stringify(readJson('worlds/manor_lake/pack.json')));
    const {kit} = load({files: {'/app/night/worlds/index.json': {worlds: []}, '/app/night/worlds/manor_lake/pack.json': pack}});
    const use = changes => { const copy = JSON.parse(JSON.stringify(pack)); for (const [slot, value] of Object.entries(changes)) { if (value === null) delete copy.scenes[slot]; else copy.scenes[slot] = value; } copy.v = ''; kit.useWorld(copy); };
    const name = spec => kit.sceneUrl(spec).split('/').pop();
    use({vote: null});
    assert.equal(name({slot: 'vote'}), 'scene_day_morning.webp', 'vote → day (its default time)');
    use({vote: null, day: null});
    assert.equal(name({slot: 'vote'}), 'scene_lobby_evening.webp', 'vote → day → lobby');
    use({out: null});
    assert.equal(name({slot: 'out'}), 'scene_night_night.webp', 'out → night');
    use({out: null, night: null});
    assert.equal(name({slot: 'out'}), 'scene_lobby_evening.webp', 'out → night → lobby');
    use({finale: null});
    assert.equal(name({slot: 'finale'}), 'scene_cover.webp', 'finale → cover');
    use({finale: null, cover: null});
    assert.equal(name({slot: 'finale'}), 'scene_title.webp', 'finale → cover → title');
    use({finale: null, cover: null, title: null});
    assert.equal(kit.sceneUrl({slot: 'finale'}), '/app/night/shell/skyline.svg', 'nothing left: the shell scene');
    use({lobby: null});
    assert.equal(kit.sceneUrl({slot: 'lobby'}), '/app/night/shell/skyline.svg', 'lobby has no chain: the shell scene');
    use({});
    assert.equal(name({slot: 'lobby', time: 'night'}), 'scene_lobby_evening.webp', 'no such time: the nearest one');
    assert.equal(name({slot: 'day', time: 'day'}), 'scene_day_day.webp', 'exact time wins');
});

test('a pack that fails to load leaves the shell: no exception, no palette, vector scene', SHIPPED, async () => {
    const {kit, doc} = load({files: realFiles(), fail: new Set(['/app/night/worlds/neon_city/pack.json'])});
    assert.equal(await kit.loadPack('neon_city'), null);
    kit.useWorld(null);
    assert.equal(kit.sceneUrl({slot: 'night', time: 'night'}), '/app/night/shell/skyline.svg');
    assert.equal(kit.world, null);
    assert.ok(!doc.documentElement.dataset.ncWorld);
    assert.equal(await kit.loadPack('../etc'), null, 'a world id is checked before any request');
    const bad = load({files: {'/app/night/worlds/index.json': {worlds: []}, '/app/night/worlds/circus/pack.json': {schema: 'other'}}});
    assert.equal(await bad.kit.loadPack('circus'), null, 'not a world pack');
    const none = load();
    assert.equal(await none.kit.worldIndex(), null, 'no index: null, not a throw');
});

test('shell backgrounds are swappable by slot (shell.json); a missing slot, file or json falls back to skyline.svg', SHIPPED, async () => {
    const {kit} = load({files: {'/app/night/shell/shell.json': {scenes: {entry: 'entry_night.webp', rooms: 'skyline.svg', invite: '../../etc/passwd', loading: 5}}}});
    assert.equal(kit.shellUrl('entry'), '/app/night/shell/skyline.svg', 'not loaded yet');
    await kit.loadShell();
    assert.equal(kit.shellUrl('entry'), '/app/night/shell/entry_night.webp');
    assert.equal(kit.shellUrl('rooms'), '/app/night/shell/skyline.svg');
    assert.equal(kit.shellUrl('invite'), '/app/night/shell/skyline.svg', 'an odd file name is ignored');
    assert.equal(kit.shellUrl('empty'), '/app/night/shell/skyline.svg', 'slot absent');
    assert.equal(kit.shellUrl('loading'), '/app/night/shell/skyline.svg');
    assert.equal(kit.sceneUrl({shell: 'entry'}), '/app/night/shell/entry_night.webp');
    const shipped = readJson('shell/shell.json');
    assert.deepEqual(Object.keys(shipped.scenes).sort(), ['empty', 'entry', 'invite', 'loading', 'rooms']);
    const files = Object.values(shipped.scenes).flatMap(value => (typeof value === 'string' ? [value] : [value.portrait, value.landscape]));
    assert.ok(files.every(file => typeof file === 'string' && fs.existsSync(path.join(DIR, 'shell', file))), 'every shipped shell picture is on disk');
});

test('nc-shell/2: a slot has a portrait and a landscape picture; the orientation follows the box, a half-filled slot borrows the other', async () => {
    const {kit} = load({files: {'/app/night/shell/shell.json': {schema: 'nc-shell/2', scenes: {
        entry: {portrait: 'shell_entry_portrait.webp', landscape: 'shell_entry_landscape.webp'},
        rooms: {landscape: 'shell_rooms_landscape.webp'},
        invite: {portrait: '../x.webp', landscape: 'shell_invite_landscape.webp'},
        empty: {portrait: 7}, loading: 'shell_loading.webp'}}}});
    await kit.loadShell();
    assert.equal(kit.shellUrl('entry', 'portrait'), '/app/night/shell/shell_entry_portrait.webp');
    assert.equal(kit.shellUrl('entry', 'landscape'), '/app/night/shell/shell_entry_landscape.webp');
    assert.equal(kit.shellUrl('entry'), '/app/night/shell/shell_entry_portrait.webp', 'no viewport known: the phone first');
    assert.equal(kit.shellUrl('rooms', 'portrait'), '/app/night/shell/shell_rooms_landscape.webp', 'only one orientation: used for both');
    assert.equal(kit.shellUrl('invite', 'portrait'), '/app/night/shell/shell_invite_landscape.webp', 'an odd file name is ignored');
    assert.equal(kit.shellUrl('empty', 'landscape'), '/app/night/shell/skyline.svg', 'nothing valid: the vector scene');
    assert.equal(kit.shellUrl('loading', 'landscape'), '/app/night/shell/shell_loading.webp', 'nc-shell/1 string: every shape');
    // a scene strip of the shell carries its slot and an orientation; the empty-state picture is a wide strip
    const strip = kit.scene({shell: 'entry', title: 'Город засыпает'});
    assert.equal(strip.dataset.shell, 'entry');
    assert.equal(strip.dataset.orient, 'portrait');
    assert.equal(strip.style.props['--img'], 'url(/app/night/shell/shell_entry_portrait.webp)');
    const pic = kit.shellPicture('entry');
    assert.equal(pic.dataset.orient, 'landscape');
    assert.equal(pic.src, '/app/night/shell/shell_entry_landscape.webp');
});

test('a screen drawn before shell.json arrived gets its picture when it does', async () => {
    const {kit} = load({files: {'/app/night/shell/shell.json': {scenes: {invite: {portrait: 'shell_invite_portrait.webp', landscape: 'shell_invite_landscape.webp'}}}}});
    const strip = kit.scene({shell: 'invite', title: 'Ссылка больше не работает'});
    assert.equal(strip.style.props['--img'], 'url(/app/night/shell/skyline.svg)', 'not loaded yet: the vector scene');
    await kit.loadShell();
    assert.equal(strip.style.props['--img'], 'url(/app/night/shell/shell_invite_portrait.webp)');
});

test('every shipped pack is complete for the client: slots, 17 portraits, emblems, frames, palette, files on disk', SHIPPED, () => {
    const index = readJson('worlds/index.json');
    assert.ok(index.worlds.length >= 11, 'the 11 built worlds and the ones added since');
    for (const entry of index.worlds) {
        const pack = readJson(`worlds/${entry.id}/pack.json`);
        assert.equal(pack.id, entry.id);
        for (const slot of ['cover', 'lobby', 'night', 'day', 'vote', 'finale']) assert.ok(pack.scenes[slot], `${entry.id}: ${slot}`);
        assert.equal(pack.portraits.length, 17, entry.id);
        const files = [pack.thumb, pack.backs.role, ...Object.values(pack.frames).map(frame => frame.file), ...Object.values(pack.factions).map(item => item.emblem),
            ...pack.portraits.map(item => item.file), ...Object.values(pack.scenes).flatMap(scene => scene.file ? [scene.file] : Object.values(scene.times || {}))];
        for (const file of files) assert.ok(fs.existsSync(path.join(DIR, 'worlds', entry.id, file)), `${entry.id}/${file}`);
        assert.equal(pack.font.display, null);
    }
});

test('the 16+ mark: chips and the story show it for the darker worlds only', () => {
    const {kit} = load();
    const plain = kit.worldChip({id: 'neon_city', title: 'Неон-Сити', accent: '#ff00aa', thumb: null}, 12);
    const adult = kit.worldChip({id: 'deep_choir', title: 'Глубинный хор', accent: null, thumb: null}, 16);
    assert.ok(!find(plain, node => String(node.className).startsWith('nc-age')));
    assert.equal(find(adult, node => String(node.className).startsWith('nc-age')).textContent, '16+');
    assert.equal(find(kit.worldChip({id: 'dead_air', title: 'Мёртвый эфир'}), node => String(node.className).startsWith('nc-age')).textContent, '16+', 'known darker world without a server mark');
    assert.equal(kit.worldAge('manor_lake'), 12);
    const eighteen = kit.worldChip({id: 'some_world', title: 'Мир'}, 18);
    assert.equal(find(eighteen, node => String(node.className).startsWith('nc-age')).textContent, '18+', 'the badge follows the value');
    assert.equal(find(adult, node => String(node.className).startsWith('nc-age')).textContent, '16+');
    assert.ok(!find(kit.worldChip({id: 'x', title: 'Мир'}, 12), node => String(node.className).startsWith('nc-age')), 'no badge for 12');
    assert.ok(!find(kit.worldChip({id: 'x', title: 'Мир'}, 7), node => String(node.className).startsWith('nc-age')), 'an odd value counts as 12');
    assert.equal(kit.worldChip(null), null);
});

test('role card: tap, Enter and Space open it once; a swipe of 40+ px opens it, the vertical one does not', () => {
    const {kit} = load();
    const cardOf = onOpen => find(kit.roleCard({face: false, onOpen}), node => String(node.className).includes('nc-rolecard'));
    let opened = 0;
    let card = cardOf(() => { opened++; });
    assert.equal(card.getAttribute('role'), 'button');
    assert.equal(card.getAttribute('tabindex'), '0');
    assert.equal(card.getAttribute('aria-expanded'), 'false');
    card.fire('click');
    assert.equal(opened, 1); assert.equal(card.getAttribute('aria-expanded'), 'true');
    card.fire('click'); card.fire('keydown', {key: 'Enter'});
    assert.equal(opened, 1, 'the card turns once');

    for (const key of ['Enter', ' ']) {
        opened = 0; card = cardOf(() => { opened++; });
        const event = {key};
        card.fire('keydown', event);
        assert.equal(opened, 1, JSON.stringify(key)); assert.equal(card.getAttribute('aria-expanded'), 'true');
    }
    opened = 0; card = cardOf(() => { opened++; });
    card.fire('keydown', {key: 'a'}); card.fire('keydown', {key: 'Tab'});
    assert.equal(opened, 0, 'other keys do nothing');

    const swipe = (card, from, to) => { card.fire('pointerdown', {clientX: from[0], clientY: from[1]}); card.fire('pointerup', {clientX: to[0], clientY: to[1]}); };
    opened = 0; card = cardOf(() => { opened++; });
    swipe(card, [100, 100], [130, 100]); assert.equal(opened, 0, '30 px is not enough');
    swipe(card, [100, 100], [160, 190]); assert.equal(opened, 0, 'more vertical than horizontal: page scroll');
    swipe(card, [100, 100], [100, 300]); assert.equal(opened, 0, 'vertical');
    card.fire('pointerdown', {clientX: 100, clientY: 100}); card.fire('pointercancel'); card.fire('pointerup', {clientX: 300, clientY: 100});
    assert.equal(opened, 0, 'a cancelled gesture (the browser took the scroll) opens nothing');
    swipe(card, [200, 100], [150, 110]);
    assert.equal(opened, 1, 'left swipe');
    assert.equal(kit.flip.dir, -1, 'the face turns up from the side of the finger');
    swipe(card, [100, 100], [400, 100]); card.fire('click');
    assert.equal(opened, 1, 'a swipe followed by the browser click turns the card once');
    const right = cardOf(() => {}); swipe(right, [100, 100], [200, 105]);
    assert.equal(kit.flip.dir, 1);

    // The open card: a horizontal swipe closes it (same as «Понятно»), a tap does not.
    let closed = 0;
    const face = find(kit.roleCard({face: true, title: 'Мафия', onClose: () => { closed++; }}), node => String(node.className).includes('nc-rolecard'));
    face.fire('click'); assert.equal(closed, 0);
    swipe(face, [100, 100], [190, 100]); assert.equal(closed, 1);
    swipe(face, [100, 100], [110, 400]); assert.equal(closed, 1);
});

test('role card CSS: whole-card target, pan-y for swipes, no flip animation under prefers-reduced-motion, direction from the finger', () => {
    assert.match(CSS, /\.nc-rolecard\.tappable,\.nc-rolecard\.swipe\{touch-action:pan-y\}/);
    assert.match(CSS, /@keyframes nc-turn\{from\{transform:perspective\(900px\) rotateY\(calc\(var\(--dir,1\) \* 90deg\)\)/);
    const reduced = /@media \(prefers-reduced-motion:reduce\)\{([^@]*)\}/.exec(CSS.replace(/\r/g, ''));
    assert.ok(reduced && /\.nc-rolecard[^{]*\{animation:none;transition:none\}/.test(reduced[1]), 'reduced motion: animation and transition off');
});

test('no grain texture anywhere in the client; shell text of the lists keeps a gap under the panel header', () => {
    assert.ok(!/grain/.test(CSS), 'night-city.css has no grain');
    assert.ok(!/grain/.test(SOURCE.replace(/\/\*[\s\S]*?\*\//g, '')), 'night-city-ui.js does not use it');
    assert.match(CSS, /:root\.nc \.nc-card>\*\+\*\{margin-top:var\(--qw-s-3\)\}/);
});
