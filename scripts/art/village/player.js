// The player's figure in the village, in two looks (owner's decision 2026-11-19): a grown-up farmer with a moustache and a
// slim farmer woman (player_looks.js draws both). The game picks the look by the account's address form: 'f' → the farmer
// woman, otherwise the farmer. Three frames — standing and two steps — face right; the game mirrors them for walking left.
// Units: farm px, feet at 0,0. viewBox -17 -48 34 52. Installed inline in qw_farm/static/app.js as VILLAGE_PLAYER_SVG
// (farmer) and VILLAGE_PLAYER_SVG_F (farmer woman): copy out/player.svg and out/player-f.svg after build_village.py, or the
// player-m.svg / player-f.svg written by preview_player_looks.py.
import {playerLookSvg} from './player_looks.js';

export function playerSvg(look = 'm') {
  return playerLookSvg(look);
}
