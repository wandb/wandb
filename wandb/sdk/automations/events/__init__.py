import time

from threading import Thread

import wandb


def watch(ev):
    digest = None
    while True:
        api = wandb.Api()
        art = api.artifact("bumblebot-1/prompts:prod")
        print(art.digest)
        if digest != art.digest:
            old_digest = digest
            digest = art.digest
            print("Saw digest", digest)
            ev.alias = "prod"
            ev.digest = digest
            if old_digest is not None:
                ev.callback(ev)

        time.sleep(4)


class Event:
    def __init__(self):
        self.alias = None
        self.digest = None

    def activate(self):
        t = Thread(target=watch, args=[self])
        t.start()


def new_alias(regex, callback):
    ev = Event()
    ev.callback = callback
    return ev
