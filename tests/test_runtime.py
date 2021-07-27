import random
import time
from wandb.proto import wandb_internal_pb2 as pb


def test_runtime(
    internal_hm,
    mocked_run,
    mock_server,
    backend_interface,
    parse_ctx,
):
    with backend_interface() as interface:

        proto_run = pb.RunRecord()
        mocked_run._make_proto_run(proto_run)

        run_start = pb.RunStartRequest()
        run_start.run.CopyFrom(proto_run)

        record = interface._make_request(run_start=run_start)
        internal_hm.handle_request_run_start(record)

        # time.sleep(x)
        # interface.publish_pause()
        # time.sleep(x)
        # interface.publish_resume()
        # time.sleep(x)
        # interface.publish_resume()
        # time.sleep(x)
        total_time = fuzzy_pause_resume(interface, 3)

    ctx_util = parse_ctx(mock_server.ctx)
    print(ctx_util.config_wandb["rt"])
    assert ctx_util.config_wandb["rt"] >= total_time


def fuzzy_pause_resume(interface, N):

    current_state = random.choice(["IP", "IR"])
    clock = [random.randint(0, 1) for _ in range(N)]
    requests = random.choices(["P", "R"], k=N)
    counter = 0
    for c, req in zip(clock, requests):
        if current_state in ["IR", "IP", "RP", "RR"]:
            if c:
                time.sleep(3)
                counter += 3
        elif current_state in ["PP", "PR"]:
            if c:
                time.sleep(3)
        print(current_state, c)
        publish = interface.publish_pause if req == "P" else interface.publish_resume
        publish()
        current_state = current_state[1] + req

    print(counter)
    return counter
