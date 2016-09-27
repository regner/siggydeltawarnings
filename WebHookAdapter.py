import json

"""
Simple adapter to format output for a type of chat service.
"""


def get_webhook_adapter(type):
    if (type == 'discord'):
        web_hook = WebHookAdapter(DiscordWebHook())
    else:
        web_hook = WebHookAdapter(SlackWebHook())

    return web_hook


class WebHook:
    def format_message(self, msg: str, routes: list): pass


class WebHookAdapter(WebHook):
    def __init__(self, webhook: WebHook):
        self.adapter = webhook

    def format_message(self, msg: str, routes: list):
        return self.adapter.format_message(msg, routes)


class SlackWebHook(WebHook):
    def _format_route(self, route):
        return '{} ({}) via {} // {} jumps // {} delta'.format(
            '<{}|{}>'.format(route['system_link'], route['system_name']),
            '<{}|{}>'.format(route['region_link'], route['region_name']),
            route['wh_system_name'],
            route['distance'],
            route['delta'],
        )

    def format_message(self, msg, routes):
        return json.dumps({
            'attachments': [
                {
                    'color': 'good',
                    'pretext': msg,
                    'fallback': msg,
                    'mrkdwn_in': ['pretext', 'fields'],
                    'fields': [{'short': False, 'value': self._format_route(x)} for x in routes],
                }
            ]
        })


class DiscordWebHook(WebHook):
    def _format_route(self, route):
        return '{} ({}) via {} // {} jumps // {} delta'.format(
            route['system_name'],
            route['region_name'],
            route['wh_system_name'],
            route['distance'],
            route['delta'],
        )

    def format_message(self, msg, routes):
        return msg + '```' + '\n'.join([self._format_route(x) for x in routes]) + '```\n'
