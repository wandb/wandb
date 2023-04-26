from wandb.sdk.lib import sock_client


def test_append():
    buffer = sock_client.SockBuffer()
    data1 = b"1234"
    buffer.put(data1, len(data1))
    assert buffer.length == 4
    data2 = b"123456"
    buffer.put(data2, len(data2))
    assert buffer.length == 10
