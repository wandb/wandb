import re
import sys

import pytest
import tqdm
import wandb


def test_tqdm(wandb_backend_spy):
    with wandb.init(settings={"console": "auto"}) as run:
        print("before progress")
        for i in tqdm.tqdm(range(10), ascii=" 123456789#"):
            print(f"progress {i}")
        print("after progress", file=sys.stderr)
        print("final progress")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)

        assert "before progress" in output[0]
        assert "error" in output[1] and bool(re.search(r"100%\|#+\| 10/10", output[1]))
        for i in range(10):
            assert f"progress {i}" in output[2 + i]
        assert "after progress" in output[12] and "error" in output[12]
        assert "final progress" in output[13]


def test_emoji(wandb_backend_spy):
    with wandb.init(settings={"console": "auto"}) as run:
        print("before emoji")
        for i in range(10):
            print(f"line-{i}-\N{GRINNING FACE}")
        print("after emoji", file=sys.stderr)

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        assert "before emoji" in output[0]
        for i in range(10):
            assert f"line-{i}-\N{GRINNING FACE}" in output[1 + i]
        assert "after emoji" in output[11] and "error" in output[11]


@pytest.mark.skip(reason="order seems to be wrong")
def test_tqdm_nested(wandb_backend_spy):
    with wandb.init(settings={"console": "auto"}) as run:
        print("before progress")
        for outer in tqdm.tqdm([10, 20, 30, 40, 50], desc=" outer", position=0):
            for inner in tqdm.tqdm(
                range(outer), desc=" inner loop", position=1, leave=False
            ):
                run.log(dict(outer=outer, inner=inner))
        print("done!")
        print("after progress", file=sys.stderr)
        print("final progress")

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)

        assert "before progress" in output[0]
        assert "error" in output[1] and bool(
            re.search(r"outer: 100%\|█+\| 5/5", output[1])
        )
        assert "done!" in output[2]
        assert "after progress" in output[3] and "error" in output[3]
        assert "final progress" in output[4]


@pytest.mark.skip(reason="capture seems wrong")
def test_tqdm_post_finish(wandb_backend_spy):
    with wandb.init(settings={"console": "auto"}) as run:
        progress_bar = tqdm.tqdm(range(5))
        progress_bar.update(2)
        run.finish()
        progress_bar.update(1)

    with wandb_backend_spy.freeze() as snapshot:
        output = snapshot.output(run_id=run.id)
        assert "error" in output[0] and bool(re.search(r"40%\|█+\| 2/5", output[0]))
