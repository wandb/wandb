"""
label full tests.
"""
import inspect
import sys

import pytest


@pytest.fixture()
def doc_inject(relay_server, wandb_init):
    m = sys.modules.get("__main__")
    main_doc = getattr(m, "__doc__", None)

    def fn(new_doc=None, labels=None, init_kwargs=None):
        init_kwargs = init_kwargs or {}
        # clean up leading whitespace
        if new_doc is not None:
            m.__doc__ = inspect.cleandoc(new_doc)
        with relay_server() as relay:
            run = wandb_init(**init_kwargs)
            if labels:
                run._label(**labels)
            run.finish()
        return relay.context, run.id

    yield fn
    if main_doc is not None:
        m.__doc__ = main_doc


def test_label_none(doc_inject):
    doc_str = None
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert "9" not in telemetry


def test_label_id_only(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              @wandbcode{my-id}
              """
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}).get("1") == "my_id"


def test_label_version(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
                @wandbcode{myid, v=v3}
              """
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "myid", "3": "v3"}


def test_label_repo(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandbcode{myid, v=3, r=repo}
              """
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "myid", "2": "repo", "3": "3"}


def test_label_unknown(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandbcode{myid, version=3, repo=myrepo, unknown=something}
              """
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "myid", "2": "myrepo", "3": "3"}


def test_label_strings(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandbcode{myid, r="thismyrepo"}
              """
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "myid", "2": "thismyrepo"}


def test_label_newline(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              //@wandbcode{myid, v=6,
              i dont read multilines, but i also dont fail for them
              """
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "myid", "3": "6"}


def test_label_id_inherit(doc_inject):
    doc_str = """
              // @wandbcode{myid}
              # @wandbcode{version=3}
              """
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "myid", "3": "3"}


def test_label_ver_drop(doc_inject):
    doc_str = """
              // @wandbcode{myid, version=9}
              # @wandbcode{version=}
              """
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "myid"}


def test_label_id_as_arg(doc_inject):
    doc_str = """
              // @wandbcode{code=my-id, version=9}
              ignore
              """
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "my_id", "3": "9"}


def test_label_no_id(doc_inject):
    doc_str = """
              // @wandbcode{repo = my-repo}
              """
    context, run_id = doc_inject(doc_str)
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"2": "my_repo"}


def test_label_disable(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
                @wandbcode{myid, v=v3}
              """
    context, run_id = doc_inject(
        doc_str,
        init_kwargs=dict(
            settings={"label_disable": True},
        ),
    )
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {}


def test_label_func_good(doc_inject):
    doc_str = "junk"
    context, run_id = doc_inject(
        doc_str,
        labels=dict(
            code="mycode",
            repo="my_repo",
            code_version="33",
        ),
    )
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "mycode", "2": "my_repo", "3": "33"}


def test_label_func_disable(doc_inject):
    context, run_id = doc_inject(
        init_kwargs=dict(
            settings={"label_disable": True},
        ),
        labels=dict(
            code="mycode",
            repo="my_repo",
            code_version="33",
        ),
    )
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {}


def test_label_func_ignore(doc_inject):
    doc_str = "junk"
    context, run_id = doc_inject(
        doc_str,
        labels=dict(
            code="mycode",
            ignorepo="badignorerepo",
            code_version="33",
        ),
    )
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "mycode", "3": "33"}


def test_label_func_ignore_key(doc_inject):
    doc_str = "junk"
    context, run_id = doc_inject(
        doc_str,
        labels=dict(
            code="mycode",
            code_version="5.3",
        ),
    )
    telemetry = context.get_run_telemetry(run_id)
    assert telemetry.get("9", {}) == {"1": "mycode"}
