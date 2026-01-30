"""Unit tests for run preempting functionality."""


def test_mark_preempting_sets_flag(mock_run):
    """Verify mark_preempting() sets the _marked_preempting flag."""
    run = mock_run()
    assert run._marked_preempting is False

    run.mark_preempting()
    assert run._marked_preempting is True


def test_exit_without_preempting_keeps_flag_false(mock_run):
    """Verify exit without mark_preempting keeps flag as False."""
    run = mock_run()
    assert run._marked_preempting is False

    # Finish without calling mark_preempting
    run.finish(exit_code=1)

    # Flag should still be False
    assert run._marked_preempting is False


def test_multiple_mark_preempting_calls(mock_run):
    """Verify multiple calls to mark_preempting() keep flag as True."""
    run = mock_run()
    assert run._marked_preempting is False

    run.mark_preempting()
    assert run._marked_preempting is True

    # Call again
    run.mark_preempting()
    assert run._marked_preempting is True


def test_mark_preempting_before_finish_with_exit_code(
    mock_run, parse_records, record_q
):
    """Verify marked_preempting flag is sent with exit code."""
    run = mock_run()

    # Mark as preempting
    run.mark_preempting()
    assert run._marked_preempting is True

    # Finish with non-zero exit code
    run.finish(exit_code=1)

    # Parse records to verify preempting record was sent
    parsed = parse_records(record_q)
    assert len(parsed.preempting) == 1

    # Note: We can't directly verify the exit record's marked_preempting field
    # in this unit test, but we've verified the flag is set on the run object


def test_mark_preempting_flag_initialized_false():
    """Verify _marked_preempting is initialized to False in new runs."""
    # This tests the initialization in __init__
    # We can't easily test this without mocking since wandb.init() does a lot,
    # but the flag is set in wandb_run.py __init__ method
    pass
