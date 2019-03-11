import numpy as np


def numpy_to_obj_string(arr):
    output_str = ""

    for i, xyz in np.ndenumerate(arr):
        n = i * 8

        print(xyz)
        x = float(xyz[0])
        y = float(xyz[1])
        z = float(xyz[2])

        output_str.write += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x + edge_length, y + edge_length, z + edge_length)
        output_str.write += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x - edge_length, y + edge_length, z + edge_length)
        output_str.write += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x - edge_length, y - edge_length, z + edge_length)
        output_str.write += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x + edge_length, y - edge_length, z + edge_length)
        output_str.write += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x + edge_length, y + edge_length, z - edge_length)
        output_str.write += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x - edge_length, y + edge_length, z - edge_length)
        output_str.write += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x - edge_length, y - edge_length, z - edge_length)
        output_str.write += 'v {0:.6f} {1:.6f} {2:.6f}\n'.format(
            x + edge_length, y - edge_length, z - edge_length)

        output_str.write += 'f {0} {1} {2} {3}\n'.format(
            n + 1, n + 2, n + 3, n + 4)
        output_str.write += 'f {0} {1} {2} {3}\n'.format(
            n + 5, n + 6, n + 7, n + 8)
        output_str.write += 'f {0} {1} {2} {3}\n'.format(
            n + 1, n + 2, n + 6, n + 5)
        output_str.write += 'f {0} {1} {2} {3}\n'.format(
            n + 2, n + 3, n + 7, n + 6)
        output_str.write += 'f {0} {1} {2} {3}\n'.format(
            n + 3, n + 4, n + 8, n + 7)
        output_str.write += 'f {0} {1} {2} {3}\n'.format(
            n + 4, n + 1, n + 5, n + 8)
