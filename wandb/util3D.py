import numpy as np


def enumdim(a, axis=0):
    a = np.asarray(a)
    leading_indices = (slice(None),) * axis
    # print(a.shape[axis])
    for i in range(a.shape[axis]):
        yield i, a[leading_indices + (i,)]


DEFAULT_EDGE_SIZE = 0.1


def xyz_numpy_to_point_cloud_obj(arr, **kwargs):
    output_str = ""
    edge_length = kwargs["edge_size"] or DEFAULT_EDGE_SIZE

    # TODO: Check speed on this one.
    for i, xyz in enumdim(arr, axis=0):
        # np.ndenumerate(iterdim(arr, axis=0)):

        n = i * 8

        x = float(xyz[0])
        y = float(xyz[1])
        z = float(xyz[2])

        output_str += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x + edge_length, y + edge_length, z + edge_length)
        output_str += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x - edge_length, y + edge_length, z + edge_length)
        output_str += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x - edge_length, y - edge_length, z + edge_length)
        output_str += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x + edge_length, y - edge_length, z + edge_length)
        output_str += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x + edge_length, y + edge_length, z - edge_length)
        output_str += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x - edge_length, y + edge_length, z - edge_length)
        output_str += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x - edge_length, y - edge_length, z - edge_length)
        output_str += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x + edge_length, y - edge_length, z - edge_length)

        output_str += 'f {0} {1} {2} {3}\n'.format(
            n + 1, n + 2, n + 3, n + 4)
        output_str += 'f {0} {1} {2} {3}\n'.format(
            n + 5, n + 6, n + 7, n + 8)
        output_str += 'f {0} {1} {2} {3}\n'.format(
            n + 1, n + 2, n + 6, n + 5)
        output_str += 'f {0} {1} {2} {3}\n'.format(
            n + 2, n + 3, n + 7, n + 6)
        output_str += 'f {0} {1} {2} {3}\n'.format(
            n + 3, n + 4, n + 8, n + 7)
        output_str += 'f {0} {1} {2} {3}\n'.format(
            n + 4, n + 1, n + 5, n + 8)

    return output_str
