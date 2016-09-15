import os
import csv
import time
import logging
import requests
import WebHookAdapter
import RouteSourceAdapter

from evelink.map import Map
from collections import deque
from collections import defaultdict
from datetime import datetime, timedelta
from fibonacci_heap_mod import Fibonacci_heap
from WebHookAdapter import get_webhook_adapter
from RouteSourceAdapter import get_route_source_adapter

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

MIN_DELTA = int(os.environ.get('MIN_DELTA', 200))
MAX_JUMPS = int(os.environ.get('MAX_JUMPS', 15))

HOME_SYSTEM_ID = int(os.environ.get('HOME_SYSTEM_ID'))
WEBHOOK_URL  = os.environ.get('WEBHOOK_URL')
WEBHOOK_TYPE = os.environ.get('WEBHOOK_TYPE')
SOURCE_TYPE  = os.environ.get('SOURCE_TYPE')
SIGGY_USERNAME = os.environ.get('SIGGY_USERNAME')
SIGGY_PASSWORD = os.environ.get('SIGGY_PASSWORD')

missing_env_text = 'Missing required environment variable {}.'

if HOME_SYSTEM_ID is None:
    raise RuntimeError(missing_env_text.format('HOME_SYSTEM_ID'))

if WEBHOOK_URL is None:
    raise RuntimeError(missing_env_text.format('WEBHOOK_URL'))

if SOURCE_TYPE != 'eve-scout':
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
    def __init__(self, web_hook: WebHookAdapter.WebHook, route_source: RouteSourceAdapter.RouteSource):

        self.route_source = route_source
        self.web_hook = web_hook

        self.max_security = 0.45

        self.starmap = {}
        self.regions = {}
        self.wormholes = set()
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

    def _update_route_data(self):
            for (names, wh) in self.route_source.get_routes():
                self.starmap[wh[0]]['name'] = names[0]
                self.starmap[wh[1]]['name'] = names[1]
                self.wormholes.add(wh)

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
            graph[k] = v['neighbors'].copy()

        for from_id, to_id in self.wormholes:
            graph[from_id].add(to_id)
            graph[to_id].add(from_id)

        results = dijkstra(graph, HOME_SYSTEM_ID, self.high_deltas)
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

    def _sort_route_list(self,routes):
        routes_list = []

        for route in routes:
            exit_system_id = self._find_exit_from_route(route)

            value = [
                route[-1],
                exit_system_id,
                len(route),
                route
            ]
            routes_list.append(value)

        routes_list.sort(key = lambda l: (l[1], l[2]))
        routes = []

        for route in routes_list:
            routes.append(route[3])

        return routes

    def _format_route_field(self, route):
        system = self.starmap[route[-1]]
        exit_system_id = self._find_exit_from_route(route)

        return {
            'system_link': self._format_dotlan_system_link(route[-1]),
            'system_name': system['name'],
            'region_link': self._format_dotlan_region_link(system['regionID']),
            'region_name': self.regions[system['regionID']],
            'wh_system_name': self.starmap[exit_system_id]['name'],
            'distance': len(route),
            'delta': self.npc_deltas[route[-1]],
        }


    def _format_message(self, routes):
        routes = self._sort_route_list(routes)
        return self.web_hook.format_message('*!! High Delta Systems Detected !!*', [self._format_route_field(x) for x in routes])

    def run(self):
        while True:
            now = datetime.utcnow()

            expire_time = datetime.utcfromtimestamp(self.npc_kills_cache_time)
            expire_time = expire_time + timedelta(seconds=30)

            if now > expire_time:
                logger.info('Starting the main run...')
                # Clearing the wormholes cache as it doesn't seem to get cleared
                # when we update the Siggy data.

                self._update_npc_kills()
                self._update_route_data()

                routes = self._find_high_delta_routes()

                if len(routes) > 0:
                    requests.post(WEBHOOK_URL, data=self._format_message(routes[:20]))
            else:
                sleep_time = expire_time - now
                logger.info('Cache time remaning: {}'.format(sleep_time))
                time.sleep(60)



if __name__ == '__main__':
    web_hook = get_webhook_adapter(WEBHOOK_TYPE)
    route_source = get_route_source_adapter(SOURCE_TYPE, username=SIGGY_USERNAME, password=SIGGY_PASSWORD, home_system_id=HOME_SYSTEM_ID)

    sdw = SiggyDeltaWarnings(web_hook, route_source)
    sdw.run()