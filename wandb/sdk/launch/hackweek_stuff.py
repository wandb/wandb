import wandb
import random


class Queue:
    ...

    @property
    def config(self):
        return {"something": ..., "requirement": ...}


class Agent:
    ...

    @property
    def config(self):
        return {
            "gpus": ...,
            "cpus": ...,
            "ram": ...,
        }


def get_queues():
    QUERY = ...
    PARAMS = {}

    api = wandb.Api()
    r = api.client.execute(QUERY, PARAMS)

    return [Queue(**spec) for spec in r]


def satisfies_requirements(queue_spec: dict, agent_spec: dict):
    return queue_spec.requirements == agent_spec.requirements


def get_valid_queues(agent: Agent):
    queues = get_queues()
    valid_queues = [q for q in queues if satisfies_requirements(q.spec, agent.spec)]
    return valid_queues


def select_queue(queues: list[Queue]):
    return random.choice(queues)


def do_stuff(agent):
    valid_queues = get_valid_queues()
    selected_queue = select_queue(valid_queues)  # get a job from the queue
    combined_config = {**selected_queue.config, **agent.config}

    return combined_config
