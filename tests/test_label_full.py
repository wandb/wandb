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
    # assert telemetry and 7 in telemetry.get("3", [])


def test_label_id_only(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              @wandb-label{my-id}
              """
    cu = doc_inject(doc_str)


def test_label_version(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
                @wandb-label{my-id, v=3}
              """
    cu = doc_inject(doc_str)


def test_label_repo(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandb-label{my-id, v=3, r=repo}
              """
    cu = doc_inject(doc_str)


def test_label_unknown(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandb-label{my-id, version=3, r=repo, unknown=something}
              """
    cu = doc_inject(doc_str)


def test_label_strings(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandb-label{my-id, r="this is my repo"}
              """
    cu = doc_inject(doc_str)


def test_label_newline(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              //@wandb-label{my-id, v=6,
              i dont read multilines, but i also dont fail for them
              """
    cu = doc_inject(doc_str)


def test_label_id_inherit(doc_inject):
    doc_str = """
              // @wandb-label{my-id}
              # @wandb-label{version=3}
              """
    cu = doc_inject(doc_str)


def test_label_id_inherit(doc_inject):
    doc_str = """
              // @wandb-label{my-id, version=9}
              # @wandb-label{version=}
              """
    cu = doc_inject(doc_str)


def test_label_id_as_arg(doc_inject):
    doc_str = """
              // @wandb-label{id=my-id, version=9}
              """
    cu = doc_inject(doc_str)


def test_label_no_id(doc_inject):
    doc_str = """
              // @wandb-label{repo=my-repo}
              """
    cu = doc_inject(doc_str)
