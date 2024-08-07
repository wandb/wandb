import itertools
import math
from typing import Tuple

import hypothesis
import numpy as np
import pytest
from hypothesis.strategies import floats, tuples
from wandb import data_types
from wandb.sdk.data_types.object_3d import quaternion_to_rotation

small_floats = floats(min_value=-1e8, max_value=1e8)
quaternions = tuples(
    small_floats,
    small_floats,
    small_floats,
    small_floats,
)


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

        v1 = tuple(p1[i] - p2[i] for i in range(3))
        v2 = tuple(p1[i] - p3[i] for i in range(3))
        v3 = tuple(p2[i] - p3[i] for i in range(3))

        dot1 = sum(v1[i] * v2[i] for i in range(3))
        dot2 = sum(v1[i] * v3[i] for i in range(3))

        # If any pair of edges is orthogonal, then it's a right triangle.
        if dot1 == pytest.approx(0) or dot2 == pytest.approx(0):
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


@hypothesis.given(xrad=small_floats, yrad=small_floats, zrad=small_floats)
def test_euler_angles(xrad: float, yrad: float, zrad: float):
    # Rotation matrices that act by pre-multiplication.
    #
    # zrot rotates the X axis toward the Y axis,
    # xrot rotates the Y axis toward the Z axis,
    # yrot rotates the Z axis toward the X axis,
    #
    # so we have a right-handed system.
    xrot = np.array(
        (
            (1, 0, 0),
            (0, math.cos(xrad), -math.sin(xrad)),
            (0, math.sin(xrad), math.cos(xrad)),
        )
    )
    yrot = np.array(
        (
            (math.cos(yrad), 0, math.sin(yrad)),
            (0, 1, 0),
            (-math.sin(yrad), 0, math.cos(yrad)),
        )
    )
    zrot = np.array(
        (
            (math.cos(zrad), -math.sin(zrad), 0),
            (math.sin(zrad), math.cos(zrad), 0),
            (0, 0, 1),
        )
    )

    quat = data_types.euler_angles(xrad, yrad, zrad)

    assert quaternion_to_rotation(quat).T == pytest.approx(zrot @ yrot @ xrot)
