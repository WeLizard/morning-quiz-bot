// Approved everyday figures. Construction crew and Pooh remain in crew.js unchanged.
import {crewResidents} from './crew-residents.js';
import {hostResidents} from './host-residents.js';
import {tricksterResidents} from './trickster-residents.js';
export function residentSvgs() {
  return {...crewResidents(), ...hostResidents(), ...tricksterResidents()};
}
