import pusherclient
import time
import json
import sys
import click
import requests
import logging
from wandb.api import Api
import wandb

pusherclient.Pusher.host = "ws-us2.pusher.com"


class Puller(object):
    def __init__(self, run_id, pod_id=None, finished=lambda: {exit()}):
        if Api().settings()['base_url'].endswith("dev"):
            self.key = 'c48d148df77404b3c278'
        else:
            self.key = 'e670693ad14e2af5f1dd'
        self.run_id = run_id
        self.pod_id = pod_id
        self.client = pusherclient.Pusher(self.key)
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
