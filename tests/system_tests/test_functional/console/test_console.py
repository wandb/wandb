import re
import sys

import pytest
import tqdm


@pytest.mark.wandb_core_only
def test_tqdm(wandb_init, relay_server):
    with relay_server() as relay:
        with wandb_init(settings={"console": "auto"}):
            print("before progress")
            for i in tqdm.tqdm(range(10), ascii=" 123456789#"):
                print(f"progress {i}")
            print("after progress", file=sys.stderr)
            print("final progress")

        output = relay.context.output[0]

        assert "before progress" in output[0]
        assert output[1].startswith("ERROR") and bool(
            re.search(r"100%\|#+\| 10/10", output[1])
        )
        for i in range(10):
            assert f"progress {i}" in output[2 + i]
        assert "after progress" in output[12] and output[12].startswith("ERROR")
        assert "final progress" in output[13]


@pytest.mark.wandb_core_only
def test_emoji(wandb_init, relay_server):
    with relay_server() as relay:
        with wandb_init(settings={"console": "auto"}):
            print("before emoji")
            for i in range(10):
                print(f"line-{i}-\N{GRINNING FACE}")
            print("after emoji", file=sys.stderr)

        output = relay.context.output[0]
        assert "before emoji" in output[0]
        for i in range(10):
            assert f"line-{i}-\N{GRINNING FACE}" in output[1 + i]
        assert "after emoji" in output[11] and output[11].startswith("ERROR")


@pytest.mark.skip(reason="order seems to be wrong")
def test_tqdm_nested(wandb_init, relay_server):
    with relay_server() as relay:
        with wandb_init(settings={"console": "auto"}) as run:
            print("before progress")
            for outer in tqdm.tqdm([10, 20, 30, 40, 50], desc=" outer", position=0):
                for inner in tqdm.tqdm(
                    range(outer), desc=" inner loop", position=1, leave=False
                ):
                    run.log(dict(outer=outer, inner=inner))
            print("done!")
            print("after progress", file=sys.stderr)
            print("final progress")

        output = relay.context.output[0]
        assert "before progress" in output[0]
        assert output[1].startswith("ERROR") and bool(
            re.search(r"outer: 100%\|█+\| 5/5", output[1])
        )
        assert "done!" in output[2]
        assert "after progress" in output[3] and output[3].startswith("ERROR")
        assert "final progress" in output[4]


@pytest.mark.skip(reason="capture seems wrong")
def test_tqdm_post_finish(wandb_init, relay_server):
    with relay_server() as relay:
        run = wandb_init(settings={"console": "auto"})
        progress_bar = tqdm.tqdm(range(5))
        progress_bar.update(2)
        run.finish()
        progress_bar.update(1)

    output = relay.context.output[0]
    assert output[0].startswith("ERROR") and bool(
        re.search(r"40%\|█+\| 2/5", output[0])
    )
