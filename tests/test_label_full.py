"""
label full tests.
"""

import inspect
import pytest
import sys

import wandb


@pytest.fixture()
def doc_inject(live_mock_server, test_settings, parse_ctx):
    m = sys.modules.get("__main__")
    main_doc = getattr(m, "__doc__", None)

    def fn(new_doc):
        # clean up leading whitespace
        if new_doc is not None:
            m.__doc__ = inspect.cleandoc(new_doc)
        run = wandb.init(settings=test_settings)
        run.finish()
        ctx_util = parse_ctx(live_mock_server.get_ctx())
        return ctx_util

    yield fn
    if main_doc is not None:
        m.__doc__ = main_doc


# from wandb.proto import wandb_telemetry_pb2 as tpb


def test_label_none(doc_inject):
    doc_str = None
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert "9" not in telemetry


def test_label_id_only(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              @wandb{my-id}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}).get("1") == "my_id"


def test_label_version(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
                @wandb{myid, v=v3}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "3": "v3"}


def test_label_repo(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandb{myid, v=3, r=repo}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "2": "repo", "3": "3"}


def test_label_unknown(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandb{myid, version=3, repo=myrepo, unknown=something}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "2": "myrepo", "3": "3"}


def test_label_strings(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandb{myid, r="thismyrepo"}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "2": "thismyrepo"}


def test_label_newline(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              //@wandb{myid, v=6,
              i dont read multilines, but i also dont fail for them
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "3": "6"}


def test_label_id_inherit(doc_inject):
    doc_str = """
              // @wandb{myid}
              # @wandb{version=3}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "3": "3"}


def test_label_ver_drop(doc_inject):
    doc_str = """
              // @wandb{myid, version=9}
              # @wandb{version=}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid"}


def test_label_id_as_arg(doc_inject):
    doc_str = """
              // @wandb{id=my-id, version=9}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "my_id", "3": "9"}


def test_label_no_id(doc_inject):
    doc_str = """
              // @wandb{repo=my-repo}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"2": "my_repo"}
