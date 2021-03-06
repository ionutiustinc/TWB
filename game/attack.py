import time
import os
import json
from core.extractors import Extractor
import logging
import time


class AttackManager:
    map = None
    village_id = None
    troopmanager = None
    wrapper = None
    targets = {}
    logger = logging.getLogger("Attacks")
    max_farms = 15
    template = {

    }
    extra_farm = []
    repman = None

    def __init__(self, wrapper=None, village_id=None, troopmanager=None, map=None):
        self.wrapper = wrapper
        self.village_id = village_id
        self.troopmanager = troopmanager
        self.map = map

    def enough_in_village(self, units):
        for u in units:
            if u not in self.troopmanager.troops:
                return "%s (0/%d)" % (u, units[u])
            if units[u] > int(self.troopmanager.troops[u]):
                return "%s (%s/%d)" % (u, self.troopmanager.troops[u], units[u])
        return False

    def run(self):
        if not self.troopmanager.can_attack or self.troopmanager.troops == {}:
            return False
        self.get_targets()
        for target in self.targets[0:self.max_farms]:
            if type(self.template) == list:
                f = False
                for template in self.template:
                    out_res = self.send_farm(target, template)
                    if out_res:
                        f = True
                        break
                if not f:
                    continue
            else:
                out_res = self.send_farm(target, self.template)
                if not out_res:
                    continue

    def send_farm(self, target, template):
        target, distance = target
        missing = self.enough_in_village(template)
        if not missing:
            cached = self.can_attack(vid=target['id'], clear=False)
            if cached:
                attack_result = self.attack(target['id'], troops=template)
                self.logger.info("Attacking %s -> %s (%s)" % (self.village_id, target['id'], str(template)))
                if attack_result:
                    for u in template:
                        self.troopmanager.troops[u] = str(int(self.troopmanager.troops[u]) - template[u])
                    self.attacked(target['id'],
                                  scout=True,
                                  safe=True,
                                  high_profile=cached['high_profile'] if type(cached) == dict else False,
                                  low_profile=cached['low_profile'] if type(cached) == dict and 'low_profile' in cached else False)
                    return True
        else:
            self.logger.debug("Not sending additional farm because not enough units: %s" % missing)
        return False

    def get_targets(self):
        output = []
        for vid in self.map.villages:
            village = self.map.villages[vid]
            if village['owner'] != "0" and vid not in self.extra_farm:
                continue
            if vid in self.extra_farm:
                get_h = time.localtime().tm_hour
                if get_h in range(0, 8) or get_h == 23:
                    self.logger.debug("Village %s will be ignored because it is player owned and attack between 23h-8h" % vid)
                    continue

            distance = self.map.get_dist(village['location'])
            output.append([village, distance])

        self.targets = sorted(output, key=lambda x: x[1])

    def attacked(self, vid, scout=False, high_profile=False, safe=True, low_profile=False):
        cache_entry = {
            "scout": scout,
            "safe": safe,
            "high_profile": high_profile,
            "low_profile": low_profile,
            "last_attack": int(time.time())
        }
        AttackCache.set_cache(vid, cache_entry)

    def scout(self, vid):
        if 'spy' not in self.troopmanager.troops or int(self.troopmanager.troops['spy']) < 5:
            self.logger.debug("Cannot scout %s at the moment because insufficient unit: spy" % vid)
            return False
        troops = {'spy': 5}
        self.attack(vid, troops=troops)
        self.attacked(vid, scout=True, safe=False)

    def can_attack(self, vid, clear=False):
        cache_entry = AttackCache.get_cache(vid)
        if not cache_entry:
            status = self.repman.safe_to_engage(vid)
            if status == 1:
                return True

            if self.troopmanager.can_scout:
                self.scout(vid)
                return False
            self.logger.warning("%s will be attacked but scouting is not possible (yet), going in blind!" % vid)
            return True

        if not cache_entry['safe'] or clear:
            if cache_entry['scout'] and self.repman:
                status = self.repman.safe_to_engage(vid)
                if status == -1:
                    self.logger.info("Checking %s: scout report not yet available" % vid)
                    return False
                if status == 0:
                    self.logger.info("%s: scout report noted enemy units, ignoring" % vid)
                    return False
                self.logger.info("%s: scout report noted no enemy units, attacking" % vid)
                return True

            self.logger.debug("%s will be ignored for attack because unsafe, set safe:true to override" % vid)
            return False

        if not cache_entry['scout'] and self.troopmanager.can_scout:
            self.scout(vid)
            return False
        min_time = 7200
        if cache_entry['high_profile']:
            min_time = 3600
        if 'low_profile' in cache_entry and cache_entry['low_profile']:
            min_time = 14400

        if cache_entry['last_attack'] + min_time > int(time.time()):
            self.logger.debug(
                "%s will be ignored because of previous attack (%d sec delay between attacks)" % (vid, min_time))
            return False
        return cache_entry

    def has_troops_available(self, troops):
        for t in troops:
            if t not in self.troopmanager.troops or int(self.troopmanager.troops[t]) < troops[t]:
                return False
        return True

    def attack(self, vid, troops=None):
        url = "game.php?village=%s&screen=place&target=%s" % (self.village_id, vid)
        pre_attack = self.wrapper.get_url(url)
        pre_data = {}
        for u in Extractor.attack_form(pre_attack):
            k, v = u
            pre_data[k] = v
        if troops:
            pre_data.update(troops)
        else:
            pre_data.update(self.troopmanager.troops)

        if vid not in self.map.map_pos:
            return False

        x, y = self.map.map_pos[vid]
        post_data = {
            'x': x,
            'y': y,
            'target_type': 'coord',
            'attack': 'Aanvallen'
        }
        pre_data.update(post_data)

        confirm_url = "game.php?village=%s&screen=place&try=confirm" % self.village_id
        conf = self.wrapper.post_url(url=confirm_url, data=pre_data)
        if '<div class="error_box">' in conf.text:
            return False
        duration = Extractor.attack_duration(conf)
        self.logger.info("[Attack] %s -> %s duration %f.1 h" %
                         (self.village_id, vid, duration / 3600))

        confirm_data = {}
        for u in Extractor.attack_form(conf):
            k, v = u
            if k == "support":
                continue
            confirm_data[k] = v
        new_data = {
            'building': 'main',
            'h': self.wrapper.last_h,
        }
        confirm_data.update(new_data)
        result = self.wrapper.get_api_action(village_id=self.village_id, action="popup_command",
                                             params={"screen": "place"}, data=confirm_data)

        return result


class AttackCache:
    @staticmethod
    def get_cache(village_id):
        t_path = os.path.join("cache", "attacks", village_id + ".json")
        if os.path.exists(t_path):
            with open(t_path, 'r') as f:
                return json.load(f)
        return None

    @staticmethod
    def set_cache(village_id, entry):
        t_path = os.path.join("cache", "attacks", village_id + ".json")
        with open(t_path, 'w') as f:
            return json.dump(entry, f)

    @staticmethod
    def cache_grab():
        output = {}
        c_path = os.path.join("cache", "attacks")
        for existing in os.listdir(c_path):
            if not existing.endswith(".json"):
                continue
            t_path = os.path.join("cache", "attacks", existing)
            with open(t_path, 'r') as f:
                output[existing.replace('.json', '')] = json.load(f)
        return output
