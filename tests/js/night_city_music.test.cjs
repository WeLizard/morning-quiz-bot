'use strict';
// «Ночной город»: the music player of the client kit (off by default, track by phase, crossfades, pause in a hidden tab, silent on errors)
// and the shipped music files. The player runs in a vm with fake <audio> elements and a manual clock; no browser.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {runInNewContext} = require('node:vm');

const root = path.resolve(__dirname, '..', '..');
const SOURCE = fs.readFileSync(path.join(root, 'web/mini_client/night-city-ui.js'), 'utf8');
const DIR = path.join(root, 'web/mini_client/night');
const readJson = file => JSON.parse(fs.readFileSync(path.join(DIR, file), 'utf8'));

const kit = (() => {
    const scope = {window: {}, document: {documentElement: {}}, URL, fetch: async () => ({ok: false, status: 404}), AbortController, Date, setTimeout, clearTimeout};
    runInNewContext(SOURCE, scope);
    return scope.window.NightCity.kit;
})();

class FakeAudio {
    constructor(url) { this.src = url; this.currentTime = 0; this.duration = 170; this.paused = true; this.plays = 0; this.listeners = {}; }
    play() { this.paused = false; this.plays++; return Promise.resolve(); }
    pause() { this.paused = true; }
    removeAttribute() { this.src = ''; }
    load() {}
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
    emit(type) { for (const handler of this.listeners[type] || []) handler({}); }
}

function player({saved = null, hidden = false, shell = ['music_shell_1.m4a', 'music_shell_2.m4a'], packs = {}, blockFirstPlay = false} = {}) {
    const store = saved == null ? {} : {'nc-music': JSON.stringify(saved)};
    const audios = [], timers = [], docListeners = {};
    const clock = {t: 1_000_000};
    const doc = {hidden, addEventListener: (type, fn) => { (docListeners[type] ||= []).push(fn); }, removeEventListener: (type, fn) => { docListeners[type] = (docListeners[type] || []).filter(item => item !== fn); }};
    const env = {
        storage: () => ({getItem: key => store[key] ?? null, setItem: (key, value) => { store[key] = value; }}),
        AudioContext: () => null, now: () => clock.t, random: () => 0.9, doc,
        makeAudio: url => {
            const audio = new FakeAudio(url);
            if (blockFirstPlay && !audios.length) audio.play = () => Promise.reject({name: 'NotAllowedError'});
            audios.push(audio);
            return audio;
        },
        setInterval: fn => { timers.push(fn); return timers.length; }, clearInterval: () => {},
        shellMusic: () => shell, loadShell: () => Promise.resolve(null), shellBase: '/app/night/shell/', worldBase: '/app/night/worlds/',
        packOf: id => packs[id] || null,
    };
    const music = kit.createMusic(env);
    const advance = seconds => { for (let n = 0; n < Math.round(seconds * 20); n++) { clock.t += 50; for (const fn of timers) fn(); } };
    const gesture = () => { for (const fn of [...(docListeners.pointerdown || [])]) fn({}); };
    return {music, audios, store, doc, docListeners, advance, gesture, clock, live: () => audios.filter(audio => audio.src && !audio.paused)};
}
const pack = (id, slots, v = 'abc123') => ({id, v, music: Object.fromEntries(slots.map(slot => [slot, {file: `music_${slot}.m4a`, duration: 100}]))});
const PACKS = {manor_lake: pack('manor_lake', ['day', 'night', 'finale']), neon_city: pack('neon_city', ['day', 'finale'])};
const url = (world, slot) => `/app/night/worlds/${world}/music_${slot}.m4a?v=abc123`;

test('music is off by default: nothing is fetched or played until the player turns it on', () => {
    const p = player({packs: PACKS});
    assert.equal(p.music.enabled, false);
    p.music.follow({shell: true});
    p.music.follow({world: 'manor_lake', status: 'night'});
    p.gesture();
    p.advance(3);
    assert.equal(p.audios.length, 0, 'no <audio> element is even created');
    assert.equal(p.store['nc-music'], undefined, 'nothing is written to storage by merely looking');
    const broken = player({saved: 'not json'});
    assert.equal(broken.music.enabled, false);
});

test('account preferences override the old local choice, wait for a gesture, and fade out', () => {
    const p = player({saved: {on: false, vol: 0.3}, packs: PACKS});
    p.music.follow({world: 'manor_lake', status: 'day'});
    p.music.applyPreferences({music: true, music_volume: 70});
    assert.equal(p.audios.length, 0);
    p.gesture();
    assert.equal(p.audios.length, 1);
    assert.equal(p.audios[0].src, url('manor_lake', 'day'));
    assert.deepEqual(JSON.parse(p.store['nc-music']), {on: false, vol: 0.3});
    p.advance(0.5);
    const mid = p.audios[0].volume;
    assert.ok(mid > 0 && mid < 0.7 * 0.7 * 0.99, 'fading in: ' + mid);
    p.advance(1.5);
    assert.ok(Math.abs(p.audios[0].volume - 0.49) < 0.01, 'full level is the volume squared: ' + p.audios[0].volume);
    p.music.applyPreferences({music: false, music_volume: 50});
    assert.equal(p.music.volume, 0.5);
    p.advance(0.7);
    assert.equal(p.music.state().voices, 0);
    assert.equal(p.audios[0].paused, true);
    p.music.applyPreferences({});
    assert.equal(p.music.enabled, false);
    assert.equal(p.music.volume, 0.3);
    assert.equal(player({saved: {on: true, vol: 0.5}}).music.volume, 0.5, 'restored');
});

test('track by phase: day for lobby / day / voting, night at night (no night → day), finale once, then silence', () => {
    const p = player({packs: PACKS});
    p.music.applyPreferences({music: true});
    const key = () => p.music.state().key;
    p.music.follow({world: 'manor_lake', status: 'lobby'});
    p.gesture();
    for (const [status, slot] of [['lobby', 'day'], ['day', 'day'], ['voting', 'day'], ['night', 'night'], ['day', 'day'], ['finished', 'finale']]) {
        p.music.follow({world: 'manor_lake', status});
        assert.equal(key(), `manor_lake/${slot}`, status);
        p.advance(2);
    }
    // a world without night: day plays at night
    p.music.follow({world: 'neon_city', status: 'night'});
    assert.equal(key(), 'neon_city/day');
    assert.equal(kit.musicSlot(PACKS.neon_city.music, 'night'), 'day');
    assert.equal(kit.musicSlot({night: {file: 'music_night.m4a'}}, 'lobby'), 'night', 'only night exists: better than nothing');
    assert.equal(kit.musicSlot({}, 'night'), null);
    assert.equal(kit.musicSlot(undefined, 'day'), null);
    // the final plays once
    p.music.follow({world: 'manor_lake', status: 'finished'});
    p.advance(2);
    const finale = p.audios.find(audio => audio.src === url('manor_lake', 'finale') && !audio.paused);
    assert.ok(finale);
    finale.emit('ended');
    assert.equal(key(), null, 'silence after the final');
    p.music.follow({world: 'manor_lake', status: 'finished'});
    p.music.follow({world: 'manor_lake', status: 'finished'});
    assert.equal(key(), null, 'the next polls do not replay it');
    assert.equal(p.music.state().finaleDone, true);
    p.music.follow({world: 'manor_lake', status: 'lobby'});
    p.music.follow({world: 'manor_lake', status: 'finished'});
    assert.equal(key(), 'manor_lake/finale', 'a new game has its own final');
    // a world whose pack has no music is silent; the shell has its own theme
    p.music.follow({world: 'circus', status: 'day'});
    assert.equal(key(), null);
    p.music.follow({world: 'manor_lake', status: 'day'});
    p.music.follow({shell: true});
    assert.equal(key(), 'shell/music_shell_2.m4a', 'one theme per session, chosen at random');
    p.music.follow({shell: true});
    assert.equal(key(), 'shell/music_shell_2.m4a');
    assert.equal(p.live().at(-1).src, '/app/night/shell/music_shell_2.m4a');
});

test('music retries on the next gesture when the browser rejects the first play', async () => {
    const p = player({packs: PACKS, blockFirstPlay: true});
    p.music.applyPreferences({music: true});
    p.music.follow({world: 'manor_lake', status: 'day'});
    p.gesture();
    await Promise.resolve();
    assert.equal(p.music.state().key, null);
    p.gesture();
    assert.equal(p.music.state().key, 'manor_lake/day');
    assert.equal(p.live().length, 1);
});

test('sound waits for a tap when it was on last time', () => {
    const p = player({saved: {on: true, vol: 0.7}, packs: PACKS});
    p.music.follow({world: 'manor_lake', status: 'lobby'});
    p.advance(2);
    assert.equal(p.audios.length, 0, 'no user action yet: silence');
    p.gesture();
    assert.equal(p.audios.length, 1);
    assert.equal(p.audios[0].src, url('manor_lake', 'day'));
    assert.equal(p.docListeners.pointerdown.length, 0, 'the tap listeners are gone');
});

test('a change of track is a smooth 1.5 s crossfade, not a cut', () => {
    const p = player({packs: PACKS});
    p.music.follow({world: 'manor_lake', status: 'day'});
    p.music.applyPreferences({music: true});
    p.gesture();
    p.advance(2);
    const day = p.audios[0];
    p.music.follow({world: 'manor_lake', status: 'night'});
    const night = p.audios[1];
    assert.equal(night.src, url('manor_lake', 'night'));
    p.advance(0.75);
    assert.ok(day.volume > 0.05 && day.volume < 0.49 && night.volume > 0.05 && night.volume < 0.49, `both audible mid-way: ${day.volume} ${night.volume}`);
    assert.equal(day.paused, false);
    p.advance(1);
    assert.equal(day.paused, true, 'the old one is gone after the fade');
    assert.ok(Math.abs(night.volume - 0.49) < 0.01);
    assert.equal(p.music.state().voices, 1);
});

test('a loop is crossfaded with itself 2.5 s before its end: no gap, no pile-up', () => {
    const p = player({packs: PACKS});
    p.music.follow({world: 'manor_lake', status: 'day'});
    p.music.applyPreferences({music: true});
    p.gesture();
    p.advance(2);
    const first = p.audios[0];
    first.currentTime = 160;                     // 10 s left: the next lap is fetched early, not started
    p.advance(0.2);
    assert.equal(p.audios.length, 2);
    assert.equal(p.audios[1].paused, true);
    first.currentTime = 167.4;                   // 2.6 s left
    p.advance(0.2);
    assert.equal(p.audios[1].paused, true);
    first.currentTime = 167.6;                   // 2.4 s left: the crossfade starts
    p.advance(0.1);
    const second = p.audios[1];
    assert.equal(second.paused, false);
    assert.equal(second.src, first.src);
    p.advance(1.2);
    first.currentTime = 168.9; second.currentTime = 1.2;
    assert.ok(first.volume > 0.05 && second.volume > 0.05, `mid-way both play: ${first.volume} ${second.volume}`);
    p.advance(1.5);
    assert.equal(first.paused, true);
    assert.equal(p.music.state().voices, 1);
    assert.equal(p.music.state().key, 'manor_lake/day');
    assert.ok(Math.abs(second.volume - 0.49) < 0.01);
    assert.equal(p.audios.length, 2, 'no third element while the second lap is young');
});

test('a hidden tab pauses the music, coming back resumes it from the same place', () => {
    const p = player({packs: PACKS});
    p.music.follow({world: 'manor_lake', status: 'night'});
    p.music.applyPreferences({music: true});
    p.gesture();
    p.advance(2);
    const audio = p.audios[0];
    audio.currentTime = 33;
    p.doc.hidden = true;
    for (const fn of p.docListeners.visibilitychange) fn();
    assert.equal(audio.paused, true);
    p.music.follow({world: 'manor_lake', status: 'night'});
    p.advance(2);
    assert.equal(audio.currentTime, 33);
    assert.equal(p.audios.length, 1, 'nothing new starts in the background');
    const plays = audio.plays;
    p.doc.hidden = false;
    for (const fn of p.docListeners.visibilitychange) fn();
    assert.equal(audio.paused, false);
    assert.equal(audio.plays, plays + 1);
    assert.equal(audio.currentTime, 33);
    assert.equal(p.music.state().key, 'manor_lake/night');
});

test('a load error is silence: no exception, no retry storm, the game goes on', () => {
    const p = player({packs: PACKS});
    p.music.follow({world: 'manor_lake', status: 'day'});
    p.music.applyPreferences({music: true});
    p.gesture();
    p.audios[0].emit('error');
    assert.equal(p.music.state().key, null);
    p.music.follow({world: 'manor_lake', status: 'day'});
    p.advance(5);
    assert.equal(p.audios.length, 1, 'the broken track is not requested again at once');
    p.music.follow({world: 'manor_lake', status: 'night'});
    assert.equal(p.music.state().key, 'manor_lake/night', 'another track still plays');
    // no Audio at all (old webview, Node): turning it on does not throw either
    const bare = kit.createMusic({storage: () => null, AudioContext: () => null, now: () => 0, random: () => 0, doc: null, setInterval: () => 1, clearInterval() {},
        makeAudio: () => { throw new Error('no Audio'); }, shellMusic: () => [], loadShell: () => null, shellBase: '', worldBase: '/w/', packOf: id => PACKS[id]});
    bare.follow({world: 'manor_lake', status: 'day'});
    assert.doesNotThrow(() => bare.applyPreferences({music: true}));
    assert.equal(bare.state().key, null);
});

test('music and volume are profile settings independent of reduced motion', () => {
    const start = SOURCE.indexOf('/* --- music'), end = SOURCE.indexOf('/* --- the persistent game header');
    assert.ok(start > 0 && end > start);
    assert.doesNotMatch(SOURCE.slice(start, end).replace(/^\/\*[\s\S]*?\*\//, ''), /reduced|matchMedia/i, 'only the header comment mentions it');
    assert.match(SOURCE, /qw:game-preferences/);
    assert.doesNotMatch(SOURCE, /id: 'nc-music/);
});

test('shipped music: every world has day / night / finale files, AAC in m4a, durations match', () => {
    const index = readJson('worlds/index.json');
    assert.ok(index.worlds.length >= 15, index.worlds.length);
    for (const world of index.worlds) {
        const data = readJson(`worlds/${world.id}/pack.json`);
        assert.ok(data.music, world.id);
        assert.deepEqual(Object.keys(data.music).sort(), ['day', 'finale', 'night'], world.id);
        for (const [slot, track] of Object.entries(data.music)) {
            assert.equal(track.file, `music_${slot}.m4a`);
            const file = path.join(DIR, 'worlds', world.id, track.file);
            const head = fs.readFileSync(file).subarray(4, 12).toString('latin1');
            assert.match(head, /^ftyp/, `${world.id}/${slot} is an MP4 container`);
            assert.ok(track.duration >= (slot === 'finale' ? 15 : 90) && track.duration <= (slot === 'finale' ? 60 : 200), `${world.id}/${slot} ${track.duration}`);
            assert.ok(fs.statSync(file).size < 3_000_000);
        }
    }
    const shell = readJson('shell/shell.json');
    assert.deepEqual(shell.music.map(track => track.file), ['music_shell_1.m4a', 'music_shell_2.m4a']);
    for (const track of shell.music) assert.ok(fs.existsSync(path.join(DIR, 'shell', track.file)));
});

test('the clock reads hours and minutes for a long window and minutes and seconds for a short phase', () => {
    assert.equal(kit.clockText(13 * 3600 + 52 * 60 + 5), '13 ч 52 м');
    assert.equal(kit.clockText(3600), '1 ч 0 м');
    assert.equal(kit.clockText(125), '2:05');
});
