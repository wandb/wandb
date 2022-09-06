"""
summary test.
"""

from typing import TYPE_CHECKING, Any, Dict, Tuple

from wandb import wandb_sdk

if TYPE_CHECKING:
    from wandb.sdk.interface.summary_record import SummaryRecord


class MockCallback:
    # current_dict: t.Dict
    # summary_record: t.Optional[SummaryRecord]

    def __init__(self, current_dict: Dict) -> None:
        self.reset(current_dict)

    def reset(self, current_dict: Dict) -> None:
        self.summary_record = None
        self.current_dict = current_dict

    def update_callback(self, summary_record: "SummaryRecord") -> None:
        self.summary_record = summary_record

    def get_current_summary_callback(self) -> Dict:
        return self.current_dict

    def check_updates(self, key: Tuple[str], value: Any) -> "MockCallback":
        assert self.summary_record is not None

        for item in self.summary_record.update:
            print("item", item.key, item.value)
            if item.key == key and item.value == value:
                return self

        raise AssertionError()

    def check_removes(self, key: Tuple[str]) -> "MockCallback":
        assert self.summary_record is not None

        for item in self.summary_record.remove:
            if item.key == key:
                return self

        raise AssertionError()


def create_summary_and_mock(
    current_dict: Dict,
) -> Tuple["wandb_sdk.Summary", "MockCallback"]:
    m = MockCallback(current_dict)
    s = wandb_sdk.Summary(
        m.get_current_summary_callback,
    )
    s._set_update_callback(
        m.update_callback,
    )

    return s, m


def test_attrib_get():
    s, _ = create_summary_and_mock({"this": 2})
    assert s.this == 2


def test_item_get():
    s, _ = create_summary_and_mock({"this": 2})
    assert s["this"] == 2


def test_cb_attrib():
    s, m = create_summary_and_mock({})
    s.this = 2
    m.check_updates(("this",), 2)


def test_cb_item():
    s, m = create_summary_and_mock({})
    s["this"] = 2
    m.check_updates(("this",), 2)


def test_cb_update():
    s, m = create_summary_and_mock({})
    s.update(dict(this=1, that=2))
    m.check_updates(("this",), 1)
    m.check_updates(("that",), 2)


def test_cb_item_nested():
    s, m = create_summary_and_mock({})
    s["this"] = 2
    m.check_updates(("this",), 2)

    m.reset({})
    s["that"] = dict(nest1=dict(nest2=4, nest2b=5))
    m.check_updates(("that",), dict(nest1=dict(nest2=4, nest2b=5)))

    m.reset({"that": {"nest1": {}}})
    s["that"]["nest1"]["nest2"] = 3
    m.check_updates(("that", "nest1", "nest2"), 3)

    m.reset({"that": {}})
    s["that"]["nest1"] = 8
    m.check_updates(("that", "nest1"), 8)

    m.reset({"that": {}})
    s["that"]["nest1a"] = dict(nest2c=9)
    m.check_updates(("that", "nest1a"), dict(nest2c=9))


def test_cb_delete_item():
    s, m = create_summary_and_mock({"this": 3})
    del s["this"]
    m.check_removes(("this",))

    m.reset({"this": {"nest1": 2}})
    del s["this"]["nest1"]
    m.check_removes(("this", "nest1"))
