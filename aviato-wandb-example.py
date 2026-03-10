"""End-to-end example: wandb + aviato integration via run.SandboxSession.

Demonstrates that run.SandboxSession automatically:
1. Injects WANDB_API_KEY, WANDB_ENTITY, WANDB_PROJECT into every sandbox
2. Tags sandboxes with the wandb run name
3. Logs each sandbox ID to the wandb run on start

Each sandbox runs a simulated "training" loop that logs metrics (noisy sin
wave) back to W&B — no manual credential setup needed.

Setup (from the wandb repo root):
    # 1. Install wandb from local checkout
    uv pip install -e .

    # 2. Install buf CLI and authenticate (needed for aviato's protobuf deps)
    brew install bufbuild/buf/buf   # macOS, or see https://buf.build/docs/installation/
    buf registry login              # opens browser

    # 3. Install aviato-client from local checkout
    uv pip install -e ../aviato-client --extra-index-url https://buf.build/gen/python

Run:
    python aviato-wandb-example.py
    DEBUG=1 python aviato-wandb-example.py   # verbose logging
"""

import logging
import os
import textwrap

if os.environ.get("DEBUG"):
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(message)s")

import aviato

import wandb

# Script that each sandbox runs — simulates training with a noisy sin wave.
# Credentials are injected automatically by the integration.
TRAIN_SCRIPT = textwrap.dedent("""\
    import math
    import random
    import wandb

    lr = {lr}
    epochs = {epochs}
    label = "{label}"

    with wandb.init(project="aviato-wandb-example", job_type="train", name=label) as run:
        for epoch in range(epochs):
            t = epoch / epochs
            # lr shifts the phase and amplitude so each sandbox traces a different curve
            loss = math.sin(t * math.pi * 2 + lr * 500) * (0.3 + lr * 50) + 0.5 + random.gauss(0, 0.05)
            acc = max(0, 1 - loss) + random.gauss(0, 0.03)
            run.log({{"epoch": epoch, "loss": loss, "accuracy": acc, "lr": lr}})
        print(f"{{label}}: final loss={{loss:.4f}}, accuracy={{acc:.4f}}")
""")

with wandb.init(
    project="aviato-wandb-example",
    job_type="orchestrator",
    settings=wandb.Settings(init_timeout=120),
) as run:
    wandb.termlog(f"W&B run: {run.url}")

    # run.SandboxSession is aviato.Session with W&B integration baked in
    with run.SandboxSession() as session:
        # --- Single sandbox ---
        wandb.termlog("single sandbox...")
        sb = session.sandbox(
            container_image="python:3.11",
            network=aviato.NetworkOptions(egress_mode="internet"),
        )
        aviato.wait([sb])
        wandb.termlog(f"  {sb.sandbox_id} RUNNING")

        sb.exec(["pip", "install", "wandb", "-q"]).result()
        result = sb.exec(
            [
                "python",
                "-c",
                TRAIN_SCRIPT.format(lr=0.01, epochs=20, label="single-sandbox"),
            ]
        ).result()
        wandb.termlog(f"  {result.stdout.strip()}")

        # --- Multiple sandboxes in parallel ---
        NUM = 3
        configs = [
            {"lr": 0.001 * (i + 1), "epochs": 20 + i * 10, "label": f"parallel-{i}"}
            for i in range(NUM)
        ]

        wandb.termlog(f"creating {NUM} sandboxes in parallel...")
        sandboxes = [
            session.sandbox(
                container_image="python:3.11",
                network=aviato.NetworkOptions(egress_mode="internet"),
            )
            for _ in range(NUM)
        ]

        aviato.wait(sandboxes)
        for s in sandboxes:
            wandb.termlog(f"  {s.sandbox_id} RUNNING")

        # Install wandb in all sandboxes (parallel)
        installs = [s.exec(["pip", "install", "wandb", "-q"]) for s in sandboxes]
        aviato.results(installs)

        # Run training in all sandboxes (parallel)
        procs = [
            s.exec(["python", "-c", TRAIN_SCRIPT.format(**cfg)])
            for s, cfg in zip(sandboxes, configs)
        ]
        for _cfg, r in zip(configs, aviato.results(procs)):
            wandb.termlog(f"  {r.stdout.strip()}")

    wandb.termlog("done — check your W&B dashboard!")
