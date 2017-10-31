import pusherclient
import time
import json
import sys
import click

pusherclient.Pusher.last_message = time.time()
pusherclient.Pusher.host = "ws-us2.pusher.com"


def connect(pusher, callback, run_id, event="lines"):
    def connect_handler(data):
        channel = pusher.subscribe("logs-" + run_id)
        channel.bind(event, callback)
    return connect_handler


def callback(data):
    pusherclient.Pusher.last_message = time.time()
    for line in json.loads(data):
        l = line["line"].split(" ")
        l.pop(0)
        sys.stdout.write(" ".join(l))
    sys.stdout.flush()


def stream_run(run_id):
    # prod: e670693ad14e2af5f1dd
    pusher = pusherclient.Pusher(
        'c48d148df77404b3c278', user_data={"cluster": "us2"})
    pusher.connection.bind('pusher:connection_established',
                           connect(pusher, callback, run_id))
    pusher.connect()
    while True:
        time.sleep(1)
        if time.time() - pusherclient.Pusher.last_message > 10:
            print(click.style("Run finished", fg="green"))
            break
