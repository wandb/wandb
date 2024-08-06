import itertools
from typing import Tuple

import hypothesis
import pytest
from hypothesis.strategies import floats, tuples
from wandb import data_types

small_floats = floats(min_value=-1e10, max_value=1e10)
quaternions = tuples(
    small_floats,
    small_floats,
    small_floats,
    small_floats,
)


def square_distance(a, b) -> float:
    return sum((a[i] - b[i]) ** 2 for i in range(3))


@hypothesis.given(
    center=tuples(small_floats, small_floats, small_floats),
    size=tuples(small_floats, small_floats, small_floats),
    orientation=quaternions,
)
def test_box3d_at_least_48_triangles(
    center: "Tuple[float, float, float]",
    size: "Tuple[float, float, float]",
    orientation: "Tuple[float, float, float, float]",
):
    # Require a nonzero quaternion.
    hypothesis.assume(any(q != pytest.approx(0) for q in orientation))

    box = data_types.box3d(
        center=center,
        size=size,
        orientation=orientation,
        color=(0, 0, 0),
    )

    # Test all 56 combinations of 3 corners.
    total_right_triangles = 0
    for i1, i2, i3 in itertools.combinations(range(8), 3):
        p1, p2, p3 = box["corners"][i1], box["corners"][i2], box["corners"][i3]

        d1 = square_distance(p1, p2)
        d2 = square_distance(p2, p3)
        d3 = square_distance(p3, p1)

        # Let d1 be the longest distance.
        if d1 < d2:
            d1, d2 = d2, d1
        if d1 < d3:
            d1, d3 = d3, d1

        # If the square of one side is the sum of the squares of the other two,
        # then it's a right triangle.
        if d2 + d3 == pytest.approx(d1):
            total_right_triangles += 1

    # If it's a box, then the triangle formed by any edge and corner is
    # a right triangle. There are at least 48 such triangles: starting
    # with any of the 12 edges, we get 24 unique triangles by pairing
    # them with one of the 2 corners on the opposite edge. The triangles
    # formed with the remaining 4 corners include 2 edges, so they
    # are double-counted, meaning there are (12 * 4) / 2 = 24 of them.
    #
    # The converse is true when all dimensions are non-zero: if 8 points
    # form at least 48 right triangles, then they form a box. Proof
    # left to the reader :)
    assert total_right_triangles >= 48


def test_box3d_unrotated():
    box = data_types.box3d(
        center=(3, 4, 5),
        size=(6, 8, 10),
        orientation=(1, 0, 0, 0),
        color=(0, 0, 0),
    )

    min_pt = list(box["corners"][0])
    max_pt = list(box["corners"][0])
    for corner in box["corners"][1:]:
        for i in range(3):
            min_pt[i] = min(min_pt[i], corner[i])
            max_pt[i] = max(max_pt[i], corner[i])

    assert min_pt == pytest.approx([0, 0, 0])
    assert max_pt == pytest.approx([6, 8, 10])


def test_box3d_permute_axes():
    # The quaternion 1 + i + j + k corresponds to a rotation of 120 degrees
    # about the axis (1, 1, 1), changing (x, y, z) => (z, x, y).
    #
    # Before rotation, the box is axis-aligned with minimum and maximum
    # coordinates ±(3, 4, 5). After rotation, the same is true, but the
    # min/max coordinates are ±(5, 3, 4). After recentering, we should
    # have a box with min/max coordinates (0, 0, 0) and (10, 6, 8).
    box = data_types.box3d(
        center=(5, 3, 4),
        size=(6, 8, 10),
        orientation=(1, 1, 1, 1),
        color=(0, 0, 0),
    )

    min_pt = list(box["corners"][0])
    max_pt = list(box["corners"][0])
    for corner in box["corners"][1:]:
        for i in range(3):
            min_pt[i] = min(min_pt[i], corner[i])
            max_pt[i] = max(max_pt[i], corner[i])

    assert min_pt == pytest.approx([0, 0, 0])
    assert max_pt == pytest.approx([10, 6, 8])
