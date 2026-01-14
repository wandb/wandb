import numpy as np
import pytest
from hypothesis import assume, given
from hypothesis.strategies import floats, tuples
from wandb import data_types

small_floats = floats(min_value=-1e5, max_value=1e5)
quaternions = tuples(
    small_floats,
    small_floats,
    small_floats,
    small_floats,
)


@given(
    center=tuples(small_floats, small_floats, small_floats),
    size=tuples(small_floats, small_floats, small_floats),
    orientation=quaternions,
)
def test_box3d_always_box(
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    orientation: tuple[float, float, float, float],
):
    # Require a nonzero quaternion.
    assume(any(q != pytest.approx(0) for q in orientation))

    box = data_types.box3d(
        center=center,
        size=size,
        orientation=orientation,
        color=(0, 0, 0),
    )
    corners = np.array(box["corners"])
    center = corners.mean(axis=0)
    dists = np.linalg.norm(corners - center, axis=1)

    # Since the implementation only uses linear transformations,
    # the box must be a parallelopiped. If a parallelopiped has
    # all points equidistant from its center, then it's a box.
    assert np.std(dists) == pytest.approx(0, abs=1e-6)


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
