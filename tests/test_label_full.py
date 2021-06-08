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

    def fn(new_doc=None, labels=None):
        # clean up leading whitespace
        if new_doc is not None:
            m.__doc__ = inspect.cleandoc(new_doc)
        run = wandb.init(settings=test_settings)
        if labels:
            run._label(**labels)
        run.finish()
        ctx_util = parse_ctx(live_mock_server.get_ctx())
        return ctx_util

    yield fn
    if main_doc is not None:
        m.__doc__ = main_doc


def test_label_none(doc_inject):
    doc_str = None
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert "9" not in telemetry


def test_label_id_only(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              @wandbcode{my-id}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}).get("1") == "my_id"


def test_label_version(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
                @wandbcode{myid, v=v3}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "3": "v3"}


def test_label_repo(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandbcode{myid, v=3, r=repo}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "2": "repo", "3": "3"}


def test_label_unknown(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandbcode{myid, version=3, repo=myrepo, unknown=something}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "2": "myrepo", "3": "3"}


def test_label_strings(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              #   @wandbcode{myid, r="thismyrepo"}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "2": "thismyrepo"}


def test_label_newline(doc_inject):
    doc_str = """
              this is a test.

              i am a doc string
              //@wandbcode{myid, v=6,
              i dont read multilines, but i also dont fail for them
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "3": "6"}


def test_label_id_inherit(doc_inject):
    doc_str = """
              // @wandbcode{myid}
              # @wandbcode{version=3}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid", "3": "3"}


def test_label_ver_drop(doc_inject):
    doc_str = """
              // @wandbcode{myid, version=9}
              # @wandbcode{version=}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "myid"}


def test_label_id_as_arg(doc_inject):
    doc_str = """
              // @wandbcode{code=my-id, version=9}
              ignore
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "my_id", "3": "9"}


def test_label_no_id(doc_inject):
    doc_str = """
              // @wandbcode{repo = my-repo}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"2": "my_repo"}


def test_label_disable(test_settings, doc_inject):
    test_settings.label_disable = True
    doc_str = """
              this is a test.

              i am a doc string
                @wandbcode{myid, v=v3}
              """
    cu = doc_inject(doc_str)
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {}


def test_label_func_good(test_settings, doc_inject):
    doc_str = "junk"
    cu = doc_inject(
        doc_str, labels=dict(code="mycode", repo="my_repo", code_version="33")
    )
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "mycode", "2": "my_repo", "3": "33"}


def test_label_func_disable(test_settings, doc_inject):
    test_settings.label_disable = True
    cu = doc_inject(labels=dict(code="mycode", repo="my_repo", code_version="33"))
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {}


def test_label_func_ignore(test_settings, doc_inject):
    doc_str = "junk"
    cu = doc_inject(
        doc_str, labels=dict(code="mycode", ignorepo="badignorerepo", code_version="33")
    )
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "mycode", "3": "33"}


def test_label_func_ignore_key(test_settings, doc_inject):
    doc_str = "junk"
    cu = doc_inject(doc_str, labels=dict(code="mycode", code_version="5.3"))
    telemetry = cu.telemetry or {}
    assert telemetry.get("9", {}) == {"1": "mycode"}
