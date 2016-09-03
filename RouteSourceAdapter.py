import requests


class RouteSource:
    def get_routes(self): pass


class RouteSourceAdapter(RouteSource):
    def __init__(self, route_source: RouteSource):
        self.adapter = route_source

    def get_routes(self):
        data = self.adapter.get_routes()
        print(data)
        return data

class EveScoutSource(RouteSource):
    def __init__(self):
        self.url = 'https://www.eve-scout.com/api/wormholes'

    def get_routes(self):
        with requests.session() as s:
            data = s.get(self.url).json()
            wormholes = set()
            for wh in data:
                from_name = wh['destinationSolarSystem']['name']
                to_name   = wh['sourceSolarSystem']['name']
                wormholes.add(
                    (
                        (from_name, to_name),
                        (int(wh['sourceSolarSystem']['id']), int(wh['destinationSolarSystem']['id']))
                    )
                )

            return wormholes


class SiggySource(RouteSource):
    def __init__(self, username: str, password: str, home_system_id: int):
        self.home_system_id = home_system_id
        self.username = username
        self.password = password
        siggy_base_url = 'https://siggy.borkedlabs.com'
        self.login_url = '{}/account/login'.format(siggy_base_url)
        self.siggy_url = '{}/siggy/siggy'.format(siggy_base_url)

    def get_routes(self):
        with requests.session() as s:
            data = {
                'username': self.username,
                'password': self.password,
            }

            s.post(self.login_url, data=data)

            data = {
                'systemID': self.home_system_id,
                'lastUpdate': 0,
                'mapOpen': True,
                'mapLastUpdate': 0,
                'forceUpdate': True,
            }

            data = s.post(self.siggy_url, data=data).json()

            wormholes = set()
            for wh in data['chainMap']['wormholes'].values():
                from_name = data['chainMap']['systems'][str(wh['from_system_id'])]['name']
                to_name   = data['chainMap']['systems'][str(wh['to_system_id'])]['name']
                wormholes.add(
                    (
                        (from_name, to_name),
                        (int(wh['from_system_id']), int(wh['to_system_id']))
                    )
                )

            return wormholes
