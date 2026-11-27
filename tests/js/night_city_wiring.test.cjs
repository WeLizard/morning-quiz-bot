'use strict';
// Wiring guard of Night City, client half (MQB-012 stage 0; the server half is tests/test_night_city_wiring.py).
// The live case client is drawn on every tab with a pack that holds one asset of each group; the guard gathers
// every picture and sound address the screens use and checks which pack groups reach the player.
// NOT_DRAWN_YET lists the groups no screen uses on 2026-11-26 (MQB-012 §1.2-1.3). It only shrinks: a group that
// starts being drawn fails the test until its line is deleted, a new group nobody draws fails too.
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const {controller, find, settle} = require('./night_case_harness.cjs');

const NOT_DRAWN_YET = {
    state: 'case-state objects (pause, no connection, archive, letter): stage 2, screens 15-23',
};

const sort = value => Array.isArray(value) ? value.map(sort) : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sort(value[key])])) : value;

function pack() {
    const files = {}, assets = {};
    const add = (id, url, alt, variants) => {
        files[url] = crypto.createHash('sha256').update(url).digest('hex');
        for (const file of Object.values(variants || {})) files[file] = crypto.createHash('sha256').update(file).digest('hex');
        assets[id] = {url, alt, ...(variants ? {variants} : {})};
    };
    add('manor_char_lawyer', 'assets/character_lawyer.webp', 'Адвокат');
    add('manor_char_lawyer__f40', 'assets/character_lawyer__f40.webp', 'Адвокат, облик');
    add('manor_char_cook', 'assets/character_cook.webp', 'Повар');
    add('manor_loc_library', 'assets/location_library_day.webp', 'Библиотека', {
        morning: 'assets/location_library_morning.webp', day: 'assets/location_library_day.webp',
        evening: 'assets/location_library_evening.webp', night: 'assets/location_library_night.webp'});
    add('manor_scene_ev_blizzard', 'assets/scene_ev_blizzard.webp', 'Метель');
    add('manor_item_key', 'assets/item_key.webp', 'Ключ');
    add('manor_state_clock', 'assets/state_clock.webp', 'Часы');
    const manifest = {schema: 'nc-assets/2', world: 'manor_lake', files, assets};
    const digest = crypto.createHash('sha256').update(JSON.stringify(sort(manifest))).digest('hex');
    return {manifest, digest, pointer: `/app/night/packs/${digest}/assets.json`};
}

function fullView({digest, pointer}) {
    const art = id => ({asset_id: id, alt: 'Картина'});
    return {game_id: 'game', mode: 'night_case', server_now: '2026-11-16T20:00:00Z', runtime_status: 'running',
        public: {world: 'manor_lake', art: {manifest_sha256: digest, manifest_url: pointer},
            looks: {lawyer: {id: 'f40', title: 'Адвокат', art: art('manor_char_lawyer__f40')}, cook: {id: 'base', title: 'Повар', art: art('manor_char_cook')}},
            clock: {window_idx: 2, window_seq: 1, phase: 'investigation'},
            locations: [{id: 'library', name: 'Библиотека', body: {text: 'Пахнет старой бумагой.'}, art: art('manor_loc_library')}],
            players: [{seat: 1, character_id: 'lawyer', title: 'Адвокат', art: art('manor_char_lawyer__f40')}],
            npcs: [{character_id: 'cook', title: 'Повар', art: art('manor_char_cook')}],
            board: [{id: 'card', kind: 'evidence', observation_id: 'obs_key', observation: {observation_id: 'obs_key', kind: 'evidence', title: 'Ключ', body: {text: 'Ключ от сарая.'}, art: art('manor_item_key')}}],
            chronicle: [{event_id: 'evt_window', kind: 'window', window_idx: 2, payload: {window_idx: 2}},
                {event_id: 'evt_scene', kind: 'scene', window_idx: 2, payload: {content_event_id: 'ev_blizzard', body: {text: 'Метель.'}}, art: art('manor_scene_ev_blizzard')}]},
        self: {actor_seq: 0, status: 'active', location: 'library', character_id: 'lawyer', ap: 3, faction: 'investigation',
            role: {title: 'Адвокат', art: art('manor_char_lawyer__f40')}, goal: {body: {text: 'Цель'}, criteria: {text: 'Критерий'}},
            nearby: [{character_id: 'cook', title: 'Повар', art: art('manor_char_cook')}], observations: [], secrets: []},
        menu: [{kind: 'choice', label: 'Осмотреть стол', quote: {kind: 'act', params: {action_id: 'inspect_desk'}, selection_id: 'sel', cost: 1}},
            {kind: 'choice', label: 'Библиотека', quote: {kind: 'move', params: {location: 'library'}, selection_id: 'sel-move', cost: 1}}]};
}

// Which pack group an address belongs to: case packs by file name, world packs (frames, backs, emblems, music) by folder.
function group(url) {
    const name = url.split('/').pop();
    if (/^character_[a-z0-9_]+__[a-z0-9]+\.webp$/.test(name)) return 'look';
    const world = /\/night\/worlds\/[a-z_]+\/(frame|back|emblem|music)_/.exec(url);
    if (world) return world[1];
    const prefix = /^(character|location|scene|item|state)_/.exec(name);
    return prefix ? {character: 'portrait', location: 'place'}[prefix[1]] || prefix[1] : 'other';
}

function addresses(host) {
    const found = new Set();
    const walk = node => {
        if (!node || typeof node !== 'object') return;
        if (node.src) found.add(String(node.src));
        for (const value of Object.values(node.style?.props || {})) {
            for (const match of String(value).matchAll(/url\(([^)]+)\)/g)) found.add(match[1].replace(/^["']|["']$/g, ''));
        }
        for (const child of node.children || []) walk(child);
    };
    walk(host);
    return found;
}

test('every pack group reaches a case screen, except the ones listed as not drawn yet', async () => {
    const art = pack();
    // In the first window the role comes as a card back that turns over (screen 6).
    const first = fullView(art); first.public.clock = {...first.public.clock, window_idx: 1};
    const reveal = controller(first, url => url === art.pointer ? art.manifest : undefined, {worldArt: true, revealRole: true});
    await settle();
    const seen = new Set(addresses(reveal.host));
    await find(reveal.host, node => node.tagName === 'button' && node.textContent === 'Перевернуть карту').click(); await settle();
    for (const url of addresses(reveal.host)) seen.add(url);
    reveal.handle.close();
    const live = controller(fullView(art), url => url === art.pointer ? art.manifest : undefined, {worldArt: true});
    await settle();
    for (const url of addresses(live.host)) seen.add(url);
    for (const label of ['Место', 'Гостиная', 'Улики', 'Досье']) {
        const tab = find(live.host, node => node.tagName === 'button' && node.textContent.trim() === label);
        assert.ok(tab, `tab ${label}`);
        await tab.click(); await settle();
        for (const url of addresses(live.host)) seen.add(url);
    }
    // Music is no picture: the player gets the world and the table state, the track is the world pack's music_<slot>.m4a.
    const slot = {night: 'night', finished: 'finale'};
    for (const place of live.kit.music.places) if (place?.world) seen.add(`/app/night/worlds/${place.world}/music_${slot[place.status] || 'day'}.m4a`);
    live.handle.close();
    for (const url of seen) assert.ok(url.startsWith(`/app/night/packs/${art.digest}/`) || url.startsWith('/app/night/'), `foreign address ${url}`);
    const drawn = new Set([...seen].map(group));
    const groups = ['portrait', 'look', 'place', 'scene', 'item', 'frame', 'back', 'emblem', 'music', 'state'];
    const missing = groups.filter(name => !drawn.has(name) && !(name in NOT_DRAWN_YET));
    const wired = Object.keys(NOT_DRAWN_YET).filter(name => drawn.has(name));
    assert.deepEqual(missing, [], `no screen draws: ${missing.join(', ')} (wire it, or list it in NOT_DRAWN_YET with a reason)`);
    assert.deepEqual(wired, [], `drawn now, delete from NOT_DRAWN_YET: ${wired.join(', ')}`);
});
