import pusherclient
import time
import json
import sys
import click
import requests
import logging
from wandb.api import Api
import wandb

api = Api()
if api.settings('base_url').endswith("dev"):
    key = 'c48d148df77404b3c278'
else:
    key = 'e670693ad14e2af5f1dd'


@staticmethod
def _generate_private_key(socket_id, key, channel_name, secret):
    client = requests.Session()
    client.auth = ('api', api.api_key)
    client.timeout = 5
    client.headers.update({
        'User-Agent': api.user_agent,
    })
    #TODO: retry
    res = client.post(api.settings('base_url') + "/pusher/auth", data={
        "socket_id": socket_id,
        "channel_name": channel_name, "entity": secret
    })
    res.raise_for_status()
    return res.json()["auth"]


# Monkey patch the client
pusherclient.Pusher._generate_private_key = _generate_private_key
pusherclient.Pusher.host = "ws-us2.pusher.com"


class AgentPuller(object):
    def __init__(self, agent, entity=None, logger=None):
        self.agent = agent
        self.entity = entity or api.settings('entity')
        self.logger = logger or logging.getLogger(__name__)
        self.last_event = None
        self.socket_id = None
        self.subscribed = False
        self.subscribing = False
        self.channel_name = "private-agent-" + self.entity
        self.client = pusherclient.Pusher(key, secret=self.entity)
        self.client.connection.bind(
            'pusher:connection_established', self._connect)

    def run(self):
        self.client.connect()
        while True:
            self.subscribed = self.subscribe()
            time.sleep(1)

    def subscribe(self):
        if self.subscribed:
            return True
        if self.socket_id and not self.subscribing:
            try:
                self.subscribing = True
                events = self.client.subscribe(self.channel_name)
                events.bind("event", self.event)
                return True
            finally:
                self.subscribing = False
        return False

    def event(self, data):
        self.last_event = time.time()
        self.logger.debug("received event")
        event = json.loads(data)
        self.agent.handle_event(event)

    # We can't subscribe in here because it swallows all exception,
    # so we subscribe in the main thread
    def _connect(self, data):
        self.logger.info(
            "Connecting to entity {0} for events".format(self.entity))
        self.socket_id = json.loads(data)["socket_id"]


class LogPuller(object):
    def __init__(self, run_id, pod_id=None, finished=lambda: {exit()}):
        self.run_id = run_id
        self.pod_id = pod_id
        self.client = pusherclient.Pusher(key)
        self.started = False
        self.last_message = None
        self.finished = finished
        self.client.connection.bind(
            'pusher:connection_established', self._connect)

    def sync(self):
        self.client.connect()
        times = 0
        while True:
            time.sleep(1)
            times += 1
            timeout = 15 if self.last_message else 30
            if self.last_message and time.time() - self.last_message > timeout:
                try:
                    pod = requests.get(
                        "http://kubed.endpoints.playground-111.cloud.goog/pods/%s" % self.pod_id).json()
                    if not pod["status"]["phase"] in ["Error", "Completed"] and times < 3600:
                        if times % 30 == 0:
                            wandb.termlog("No output from process.  Current status %s, retrying in 30 seconds..." %
                                          pod["status"]["phase"])
                    else:
                        break
                except:
                    logging.error(sys.exc_info())
            elif not self.last_message and times >= 60:
                wandb.termlog(
                    "No logs available \U0001F612 try reconnecting with `wandb logs %s`" % self.run_id)
                break

    def lines(self, data):
        self.last_message = time.time()
        for line in json.loads(data):
            l = line["line"].split(" ")
            l.pop(0)
            sys.stdout.write(" ".join(l))
        sys.stdout.flush()

    def _connect(self, data):
        logs = self.client.subscribe("logs-" + self.run_id)
        logs.bind("lines", self.lines)
