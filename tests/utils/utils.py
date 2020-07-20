import os
import socket


def subdict(d, expected_dict):
    """Return a new dict with only the items from `d` whose keys occur in `expected_dict`.
    """
    return {k: v for k, v in d.items() if k in expected_dict}


def fixture_open(path):
    """Returns an opened fixture file"""
    return open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "fixtures", path))


def notebook_path(path):
    """Returns the path to a notebook"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "notebooks", path)


def free_port():
    sock = socket.socket()
    sock.bind(('', 0))

    _, port = sock.getsockname()
    return port


def assert_deep_lists_equal(a, b, indices=None):
    try:
        assert a == b
    except ValueError:
        assert len(a) == len(b)

        # pytest's list diffing breaks at 4d so we track them ourselves
        if indices is None:
            indices = []
            top = True
        else:
            top = False

        for i, (x, y) in enumerate(zip(a, b)):
            try:
                assert_deep_lists_equal(x, y, indices)
            except AssertionError:
                indices.append(i)
                raise
            finally:
                if top and indices:
                    print('Diff at index: %s' % list(reversed(indices)))