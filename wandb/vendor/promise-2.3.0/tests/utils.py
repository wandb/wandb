def assert_exception(exception, expected_exception_cls, expected_message):
    assert isinstance(exception, expected_exception_cls)
    assert str(exception) == expected_message
