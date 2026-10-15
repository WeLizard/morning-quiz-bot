"""Pure expedition rules. Offline collection is never proof of a claim."""
from dataclasses import dataclass
from hashlib import sha256
import json


@dataclass(frozen=True)
class ExpeditionStage:
    id: str
    campaign_id: str
    previous: tuple[str, ...]
    goals: frozenset[str]
    craft: frozenset[str]
    points: int
    seal: str


def catalog_revision(raw):
    return sha256(json.dumps(raw, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False).encode('utf-8')).hexdigest()


def expedition_stages(raw):
    result = {}
    elements = {item['id'] for item in raw['elements']}
    craft_results = {item['result'] for item in raw['recipes']}
    for campaign in raw.get('campaigns', []):
        previous = []
        for item in campaign['stages']:
            goals, craft = frozenset(item['goals']), frozenset(item.get('craft', []))
            points, seal = item['reward']['points'], item['reward']['seal']
            if (item['id'] in result or not goals or not goals <= elements
                    or not craft <= craft_results or type(points) is not int
                    or not 0 <= points <= 100000 or not isinstance(seal, str)):
                raise ValueError('Invalid expedition catalog')
            result[item['id']] = ExpeditionStage(item['id'], campaign['id'],
                tuple(previous), goals, craft, points, seal)
            previous.append(item['id'])
    return result


def validate_stage(stage, *, claimed, verified_discovered, verified_crafted, recipes):
    if not set(stage.previous) <= set(claimed):
        raise ValueError('Сначала заверши предыдущие этапы экспедиции')
    if not stage.goals <= set(verified_discovered):
        raise ValueError('Открытия этапа ещё не подтверждены сервером')
    results = {recipes[key][2] for key in verified_crafted if key in recipes}
    if not stage.craft <= results:
        raise ValueError('Эксперимент этапа ещё не подтверждён сервером')
