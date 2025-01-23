from wandb.sdk.internal import tb_watcher


class TestIsTfEventsFileCreatedBy:
    def test_simple(self):
        assert tb_watcher.is_tfevents_file_created_by(
            "out.writer.tfevents.193.me.94.5", "me", 193
        )

    def test_no_tfevents(self):
        assert (
            tb_watcher.is_tfevents_file_created_by(
                "out.writer.tfevent.193.me.94.5", "me", 193
            )
            is False
        )

    def test_short_prefix(self):
        assert (
            tb_watcher.is_tfevents_file_created_by("tfevents.193.me.94.5", "me", 193)
            is True
        )

    def test_too_early(self):
        assert (
            tb_watcher.is_tfevents_file_created_by("tfevents.192.me.94.5", "me", 193)
            is False
        )

    def test_dotted_hostname(self):
        assert (
            tb_watcher.is_tfevents_file_created_by(
                "tfevents.193.me.you.us.94.5", "me.you.us", 193
            )
            is True
        )

    def test_dotted_hostname_short(self):
        assert (
            tb_watcher.is_tfevents_file_created_by(
                "tfevents.193.me.you", "me.you.us", 193
            )
            is False
        )

    def test_invalid_time(self):
        assert (
            tb_watcher.is_tfevents_file_created_by(
                "tfevents.allo!.me.you", "me.you.us", 193
            )
            is False
        )

    def test_way_too_short(self):
        assert tb_watcher.is_tfevents_file_created_by("dir", "me.you.us", 193) is False

    def test_inverted(self):
        assert (
            tb_watcher.is_tfevents_file_created_by("me.193.tfevents", "me", 193)
            is False
        )
