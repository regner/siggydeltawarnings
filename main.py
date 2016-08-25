

import os
import csv
import json
import time
import logging
import requests

from evelink.map import Map
from collections import deque
from collections import defaultdict
from datetime import datetime, timedelta
from fibonacci_heap_mod import Fibonacci_heap


logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

MIN_DELTA = int(os.environ.get('MIN_DELTA', 150))
MAX_JUMPS = int(os.environ.get('MAX_JUMPS', 20))

HOME_SYSTEM_ID = int(os.environ.get('HOME_SYSTEM_ID'))
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK')
SIGGY_USERNAME = os.environ.get('SIGGY_USERNAME')
SIGGY_PASSWORD = os.environ.get('SIGGY_PASSWORD')

missing_env_text = 'Missing required environment variable {}.'

if HOME_SYSTEM_ID is None:
    raise RuntimeError(missing_env_text.format('HOME_SYSTEM_ID'))

if SLACK_WEBHOOK is None:
    raise RuntimeError(missing_env_text.format('SLACK_WEBHOOK'))

if SIGGY_USERNAME is None:
    raise RuntimeError(missing_env_text.format('SIGGY_USERNAME'))

if SIGGY_PASSWORD is None:
    raise RuntimeError(missing_env_text.format('SIGGY_PASSWORD'))


def path(prev, start, end):
    s = deque([])
    u = end

    while u != start:
        s.appendleft(u)
        
        if u not in prev:
            return []
        u = prev[u]

    s.appendleft(start)

    return list(s)


def dijkstra(graph, start, ends):
    prev = {}
    costs = {}
    entry = {}

    remaining = set(ends)

    costs[start] = 0.0

    q = Fibonacci_heap()
    entry[start] = q.enqueue(start, 0.0)

    while q:
        u = q.dequeue_min().get_value()

        if u in remaining:
            remaining.remove(u)

        if not remaining:
            break

        for v in graph[u]:
            if v in prev:
                continue

            new_cost = costs[u] + 1

            if v in costs and new_cost < costs[v]:
                costs[v] = new_cost
                prev[v] = u
                q.decrease_key(entry[v], costs[v])

            if v not in costs:
                costs[v] = new_cost
                prev[v] = u
                entry[v] = q.enqueue(v, costs[v])

    result = []
    for end in ends:
        result.append(path(prev, start, end))

    return result


class SiggyDeltaWarnings(object):
    def __init__(self):
        
        siggy_base_url = 'https://siggy.borkedlabs.com'
        self.login_url = '{}/account/login'.format(siggy_base_url)
        self.siggy_url = '{}/siggy/siggy'.format(siggy_base_url)
        self.max_security = 0.5

        self.starmap = {}
        self.regions = {}
        self.wormholes = {}
        self.npc_kills = {}
        self.npc_deltas = defaultdict(int)
        self.npc_kills_cache_time = datetime.utcnow()
        self.high_deltas = set()

        self._load_starmap()
        self._update_npc_kills()

    def _load_starmap(self):
        self.starmap = {}

        systems_file = 'mapSolarSystems.csv'
        jumps_file = 'mapSolarSystemJumps.csv'
        regions_file = 'mapRegions.csv'

        if not os.path.isfile(systems_file):
            raise RuntimeError('missing data: {}'.format(systems_file))
            
        if not os.path.isfile(jumps_file):
            raise RuntimeError('missing data: {}'.format(jumps_file))
            
        if not os.path.isfile(regions_file):
            raise RuntimeError('missing data: {}'.format(regions_file))

        with open(systems_file, 'r') as file:
            systems_csv = csv.DictReader(file)

            for system in systems_csv:
                self.starmap[int(system['solarSystemID'])] = {
                    'name': system['solarSystemName'],
                    'security': float(system['security']),
                    'neighbors': set(),
                    'regionID': int(system['regionID']),
                }

        with open(jumps_file, 'r') as file:
            jumps_csv = csv.DictReader(file)

            for jump in jumps_csv:
                self.starmap[int(jump['fromSolarSystemID'])]['neighbors'].add(
                    int(jump['toSolarSystemID'])
                )

        with open(regions_file, 'r') as file:
            regions_csv = csv.DictReader(file)

            for region in regions_csv:
                self.regions[int(region['regionID'])] = region['regionName']

    def _update_siggy_data(self):
        with requests.session() as s:
            data = {
                'username': SIGGY_USERNAME,
                'password': SIGGY_PASSWORD,
            }

            s.post('https://siggy.borkedlabs.com/account/login', data=data)
            
            data = {
                'systemID': 31001744,
                'lastUpdate': 0,
                'mapOpen': True,
                'mapLastUpdate': 0,
                'forceUpdate': True,
            }

            response = s.post(self.siggy_url, data=data)
            siggy_data = response.json()

            wormholes = set()
            for wh in siggy_data['chainMap']['wormholes'].values():
                wormholes.add((
                    int(wh['from_system_id']),
                    int(wh['to_system_id'])
                ))

            self.wormholes = wormholes

            for k, v in siggy_data['chainMap']['systems'].items():
                if v['displayName'] is not '':
                    self.starmap[int(k)]['name'] = v['displayName']

    def _update_npc_kills(self):
        kills = Map().kills_by_system()
        self.high_deltas = set()

        for system in kills.result[0].values():
            system_id = system['id']

            if system_id in self.npc_kills:
                delta = system['faction'] - self.npc_kills[system_id]
                self.npc_deltas[system_id] = delta

                if delta >= MIN_DELTA:
                    if self.starmap[system_id]['security'] < self.max_security:
                        self.high_deltas.add(system_id)

            self.npc_kills[system_id] = system['faction']

        self.npc_kills_cache_time = kills.expires

    def _find_high_delta_routes(self):
        graph = {}

        for k, v in self.starmap.items():
            graph[k] = v['neighbors']

        for from_id, to_id in self.wormholes:
            graph[from_id].add(to_id)
            graph[to_id].add(from_id)

        results = dijkstra(graph, HOME_SYSTEM_ID, self.high_deltas)
        # results = dijkstra(graph, HOME_SYSTEM_ID, [30000142, 30002187])

        trimmed_results = []

        for route in results:
            if len(route) <= MAX_JUMPS:
                trimmed_results.append(route)

        return trimmed_results

    @staticmethod
    def _find_exit_from_route(route):
        for system_id in route[::-1]:
            if system_id > 31000000:
                return system_id

    def _format_dotlan_system_link(self, system_id):
        system_name = self.starmap[system_id]['name'].replace(' ', '_')

        region_id = self.starmap[system_id]['regionID']
        region_name = self.regions[region_id].replace(' ', '_')

        return 'http://evemaps.dotlan.net/map/{}/{}#npc_delta'.format(
            region_name,
            system_name
        )

    def _format_dotlan_region_link(self, region_id):
        region_name = self.regions[region_id].replace(' ', '_')

        return 'http://evemaps.dotlan.net/map/{}#npc_delta'.format(region_name)

    def _format_route_field(self, route):
        system = self.starmap[route[-1]]
        system_link = '<{}|{}>'.format(
            self._format_dotlan_system_link(route[-1]),
            system['name']
        )

        region_link = '<{}|{}>'.format(
            self._format_dotlan_region_link(system['regionID']),
            self.regions[system['regionID']]
        )

        exit_system_id = self._find_exit_from_route(route)


        value = '{} ({}) via {} // {} jumps // {} delta'.format(
            system_link,
            region_link,
            self.starmap[exit_system_id]['name'],
            len(route),
            self.npc_deltas[route[-1]]
        )

        return {
            'value': value,
            'short': False,
        }

    def _format_slack_message(self, routes):
        title = '*!! High Delta Systems Detected !!*'

        return {
            'attachments': [
                {
                    'color': 'good',
                    'pretext': title,
                    'fallback': title,
                    'mrkdwn_in': ['pretext', 'fields'],
                    'fields': [self._format_route_field(x) for x in routes],
                }
            ]
        }

    def run(self):
        while True:
            now = datetime.utcnow()

            expire_time = datetime.utcfromtimestamp(self.npc_kills_cache_time)
            expire_time = expire_time + timedelta(seconds=30)

            if now > expire_time:
                logger.info('Starting the main run...')
                self._update_npc_kills()
                self._update_siggy_data()

                routes = self._find_high_delta_routes()
                if len(routes) > 0:
                    slack_msg = self._format_slack_message(routes)
                    requests.post(SLACK_WEBHOOK, data=json.dumps(slack_msg))

            else:
                sleep_time = expire_time - now
                logger.info('Cache time remaning: {}'.format(sleep_time))
                time.sleep(60)


if __name__ == '__main__':
    sdw = SiggyDeltaWarnings()
    sdw.run()
