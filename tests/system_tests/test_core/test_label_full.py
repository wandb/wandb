"""label full tests."""

import inspect
import sys

import pytest
import wandb


@pytest.fixture()
def doc_inject(user):
    m = sys.modules.get("__main__")
    main_doc = getattr(m, "__doc__", None)

    def fn(new_doc=None, labels=None, init_kwargs=None):
        init_kwargs = init_kwargs or {}
        # clean up leading whitespace
        if new_doc is not None:
            m.__doc__ = inspect.cleandoc(new_doc)
        with wandb.init(**init_kwargs) as run:
            if labels:
                run._label(**labels)

        return run.id

    yield fn
    if main_doc is not None:
        m.__doc__ = main_doc


def test_label_none(doc_inject, wandb_backend_spy):
    doc_str = None
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert "9" not in telemetry


def test_label_id_only(doc_inject, wandb_backend_spy):
    doc_str = """
              this is a test.

              i am a doc string
              @wandbcode{my-id}
              """
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}).get("1") == "my_id"


def test_label_version(doc_inject, wandb_backend_spy):
    doc_str = """
              this is a test.

              i am a doc string
                @wandbcode{myid, v=v3}
              """
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "myid", "3": "v3"}


def test_label_repo(doc_inject, wandb_backend_spy):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandbcode{myid, v=3, r=repo}
              """
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "myid", "2": "repo", "3": "3"}


def test_label_unknown(doc_inject, wandb_backend_spy):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandbcode{myid, version=3, repo=myrepo, unknown=something}
              """
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "myid", "2": "myrepo", "3": "3"}


def test_label_strings(doc_inject, wandb_backend_spy):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandbcode{myid, r="thismyrepo"}
              """
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "myid", "2": "thismyrepo"}


def test_label_newline(doc_inject, wandb_backend_spy):
    doc_str = """
              this is a test.

              i am a doc string
              //@wandbcode{myid, v=6,
              i dont read multilines, but i also dont fail for them
              """
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "myid", "3": "6"}


def test_label_id_inherit(doc_inject, wandb_backend_spy):
    doc_str = """
              // @wandbcode{myid}
              # @wandbcode{version=3}
              """
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "myid", "3": "3"}


def test_label_ver_drop(doc_inject, wandb_backend_spy):
    doc_str = """
              // @wandbcode{myid, version=9}
              # @wandbcode{version=}
              """
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "myid"}


def test_label_id_as_arg(doc_inject, wandb_backend_spy):
    doc_str = """
              // @wandbcode{code=my-id, version=9}
              ignore
              """
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "my_id", "3": "9"}


def test_label_no_id(doc_inject, wandb_backend_spy):
    doc_str = """
              // @wandbcode{repo = my-repo}
              """
    run_id = doc_inject(doc_str)
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"2": "my_repo"}


def test_label_disable(doc_inject, wandb_backend_spy):
    doc_str = """
              this is a test.

              i am a doc string
                @wandbcode{myid, v=v3}
              """
    run_id = doc_inject(
        doc_str,
        init_kwargs=dict(
            settings={"label_disable": True},
        ),
    )
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {}


def test_label_func_good(doc_inject, wandb_backend_spy):
    doc_str = "junk"
    run_id = doc_inject(
        doc_str,
        labels=dict(
            code="mycode",
            repo="my_repo",
            code_version="33",
        ),
    )
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "mycode", "2": "my_repo", "3": "33"}


def test_label_func_disable(doc_inject, wandb_backend_spy):
    run_id = doc_inject(
        init_kwargs=dict(
            settings={"label_disable": True},
        ),
        labels=dict(
            code="mycode",
            repo="my_repo",
            code_version="33",
        ),
    )
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {}


def test_label_func_ignore(doc_inject, wandb_backend_spy):
    doc_str = "junk"
    run_id = doc_inject(
        doc_str,
        labels=dict(
            code="mycode",
            ignorepo="badignorerepo",
            code_version="33",
        ),
    )
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "mycode", "3": "33"}


def test_label_func_ignore_key(doc_inject, wandb_backend_spy):
    doc_str = "junk"
    run_id = doc_inject(
        doc_str,
        labels=dict(
            code="mycode",
            code_version="5.3",
        ),
    )
    with wandb_backend_spy.freeze() as snapshot:
        telemetry = snapshot.telemetry(run_id=run_id)
        assert telemetry.get("9", {}) == {"1": "mycode"}
