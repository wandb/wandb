package leet

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestExpandedSidebarWidth(t *testing.T) {
	// No override: golden-ratio default.
	require.Equal(t, 76, expandedSidebarWidth(200, false, 0)) // 200 * 0.382
	require.Equal(t, 47, expandedSidebarWidth(200, true, 0))  // 200 * 0.236

	// Override fraction of terminal width.
	require.Equal(t, 50, expandedSidebarWidth(200, false, 0.25))

	// Overrides can go below the default minimum, but not the drag minimum.
	require.Equal(t, sidebarDragMinWidth, expandedSidebarWidth(200, false, 0.05))

	// The main content column keeps its minimum width.
	require.Equal(t, 200-mainDragMinWidth, expandedSidebarWidth(200, false, 0.99))
}

func TestPaneHeightFor(t *testing.T) {
	require.Equal(t, 17, paneHeightFor(0, 60, 17))
	require.Equal(t, 30, paneHeightFor(0.5, 60, 17))
}

func TestFitSidebarFractions(t *testing.T) {
	// Jointly valid overrides pass through unchanged.
	l, r := fitSidebarFractions(200, true, true, 0.3, 0.3)
	require.Equal(t, 0.3, l)
	require.Equal(t, 0.3, r)

	// Defaults are never adjusted.
	l, r = fitSidebarFractions(200, true, true, 0, 0)
	require.Zero(t, l)
	require.Zero(t, r)

	// A lone override shrinks against the opposite default width.
	l, r = fitSidebarFractions(200, true, true, 0.9, 0)
	require.Zero(t, r)
	lw := expandedSidebarWidth(200, true, l)
	rw := expandedSidebarWidth(200, true, 0)
	require.LessOrEqual(t, lw+rw, 200-mainDragMinWidth)

	// Two fat overrides shrink to fit jointly.
	l, r = fitSidebarFractions(200, true, true, 0.9, 0.9)
	lw = expandedSidebarWidth(200, true, l)
	rw = expandedSidebarWidth(200, true, r)
	require.LessOrEqual(t, lw+rw, 200-mainDragMinWidth)

	// A hidden side leaves the other side's override alone.
	l, r = fitSidebarFractions(200, true, false, 0.9, 0.9)
	require.Equal(t, 0.9, l)
	require.Equal(t, 0.9, r)
}

func TestFitStackHeights(t *testing.T) {
	// Within budget: untouched.
	h := []int{10, 10}
	fitStackHeights(h, []int{3, 3}, 30)
	require.Equal(t, []int{10, 10}, h)

	// Over budget: shrunk to exactly the budget, never below the minimums.
	// The pane floors would re-inflate anything below them, so the fit must
	// land on values SetExpandedHeight will keep.
	h = []int{12, 12}
	fitStackHeights(h, []int{10, 3}, 16)
	require.Equal(t, 16, h[0]+h[1])
	require.GreaterOrEqual(t, h[0], 10)
	require.GreaterOrEqual(t, h[1], 3)

	// Even the minimums exceed the budget: fall back to the minimums.
	h = []int{25, 25}
	fitStackHeights(h, []int{10, 3}, 5)
	require.Equal(t, []int{10, 3}, h)

	// Invisible panes (zero height) contribute nothing and stay zero.
	h = []int{0, 25}
	fitStackHeights(h, []int{10, 3}, 12)
	require.Equal(t, []int{0, 12}, h)
}
