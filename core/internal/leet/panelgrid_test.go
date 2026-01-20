package leet_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

// TestEffectiveGridSize_ClampsToAvailableSpace tests that grid size is clamped
// to fit within available space.
func TestEffectiveGridSize_ClampsToAvailableSpace(t *testing.T) {
	spec := leet.GridSpec{
		Rows:        3,
		Cols:        4,
		MinCellW:    20,
		MinCellH:    10,
		HeaderLines: 2,
	}

	// With padding: minWWithPad = 20 + 2 = 22, minHWithPad = 10 + 2 + 1 = 13
	// Available space after header: 100 - 2 = 98
	// Max cols: 120 / 22 = 5, max rows: 98 / 13 = 7
	// Requested 3x4, both fit, so should get 3x4
	size := leet.EffectiveGridSize(120, 100, spec)
	require.Equal(t, 3, size.Rows)
	require.Equal(t, 4, size.Cols)

	// Too narrow: only 1 column fits
	size = leet.EffectiveGridSize(30, 100, spec)
	require.Equal(t, 3, size.Rows)
	require.Equal(t, 1, size.Cols)

	// Too short: only 1 row fits (after header)
	size = leet.EffectiveGridSize(120, 15, spec)
	require.Equal(t, 1, size.Rows)
	require.Equal(t, 4, size.Cols)

	// Both dimensions too small: should clamp to 1x1
	size = leet.EffectiveGridSize(25, 15, spec)
	require.Equal(t, 1, size.Rows)
	require.Equal(t, 1, size.Cols)
}

func TestComputeGridDims_CalculatesCorrectDimensions(t *testing.T) {
	spec := leet.GridSpec{
		Rows:        2,
		Cols:        3,
		MinCellW:    20,
		MinCellH:    10,
		HeaderLines: 0,
	}

	dims := leet.ComputeGridDims(120, 60, spec)

	// 120 / 3 cols = 40 per cell with padding
	require.Equal(t, 40, dims.CellWWithPadding)
	// 60 / 2 rows = 30 per cell with padding
	require.Equal(t, 30, dims.CellHWithPadding)

	// Inner dimensions: cellWWithPad - ChartBorderSize (2)
	// Should be at least MinCellW (20)
	require.GreaterOrEqual(t, dims.CellW, 20)
	require.GreaterOrEqual(t, dims.CellH, 10)
}

func TestComputeGridDims_RespectsMinimums(t *testing.T) {
	spec := leet.GridSpec{
		Rows:        2,
		Cols:        2,
		MinCellW:    50,
		MinCellH:    30,
		HeaderLines: 0,
	}

	// Very small viewport - should still respect minimums
	dims := leet.ComputeGridDims(30, 20, spec)

	require.GreaterOrEqual(t, dims.CellW, spec.MinCellW)
	require.GreaterOrEqual(t, dims.CellH, spec.MinCellH)
}

func TestGridNavigator_Navigate(t *testing.T) {
	var nav leet.GridNavigator
	nav.UpdateTotalPages(30, 10) // 3 pages

	// Initial page is 0
	require.Equal(t, 0, nav.CurrentPage())

	// Navigate forward
	changed := nav.Navigate(1)
	require.True(t, changed)
	require.Equal(t, 1, nav.CurrentPage())

	// Navigate forward again
	changed = nav.Navigate(1)
	require.True(t, changed)
	require.Equal(t, 2, nav.CurrentPage())

	// Navigate forward - should wrap to page 0
	changed = nav.Navigate(1)
	require.True(t, changed)
	require.Equal(t, 0, nav.CurrentPage())

	// Navigate backward - should wrap to last page
	changed = nav.Navigate(-1)
	require.True(t, changed)
	require.Equal(t, 2, nav.CurrentPage())

	// Navigate backward
	changed = nav.Navigate(-1)
	require.True(t, changed)
	require.Equal(t, 1, nav.CurrentPage())
}

func TestGridNavigator_NavigateSinglePage(t *testing.T) {
	var nav leet.GridNavigator
	nav.UpdateTotalPages(5, 10) // Only 1 page

	changed := nav.Navigate(1)
	require.False(t, changed)
	require.Equal(t, 0, nav.CurrentPage())

	changed = nav.Navigate(-1)
	require.False(t, changed)
	require.Equal(t, 0, nav.CurrentPage())
}

func TestGridNavigator_UpdateTotalPages(t *testing.T) {
	var nav leet.GridNavigator

	// Start with 3 pages
	nav.UpdateTotalPages(30, 10)
	require.Equal(t, 3, nav.TotalPages())
	require.Equal(t, 0, nav.CurrentPage())

	// Navigate to last page
	nav.Navigate(1)
	nav.Navigate(1)
	require.Equal(t, 2, nav.CurrentPage())

	// Reduce to 2 pages - current page should be clamped
	nav.UpdateTotalPages(15, 10)
	require.Equal(t, 2, nav.TotalPages())
	require.Equal(t, 1, nav.CurrentPage()) // Clamped from 2 to 1

	// Reduce to 1 page
	nav.UpdateTotalPages(5, 10)
	require.Equal(t, 1, nav.TotalPages())
	require.Equal(t, 0, nav.CurrentPage()) // Clamped to 0

	// Zero items
	nav.UpdateTotalPages(0, 10)
	require.Equal(t, 0, nav.TotalPages())
	require.Equal(t, 0, nav.CurrentPage())
}

func TestGridNavigator_GetPageBounds(t *testing.T) {
	var nav leet.GridNavigator
	nav.UpdateTotalPages(25, 10) // 3 pages

	// Page 0: items 0-9
	start, end := nav.PageBounds(25, 10)
	require.Equal(t, 0, start)
	require.Equal(t, 10, end)

	// Page 1: items 10-19
	nav.Navigate(1)
	start, end = nav.PageBounds(25, 10)
	require.Equal(t, 10, start)
	require.Equal(t, 20, end)

	// Page 2: items 20-24 (partial page)
	nav.Navigate(1)
	start, end = nav.PageBounds(25, 10)
	require.Equal(t, 20, start)
	require.Equal(t, 25, end)
}

func TestGridNavigator_GetPageBoundsEdgeCases(t *testing.T) {
	var nav leet.GridNavigator

	// Empty list
	nav.UpdateTotalPages(0, 10)
	start, end := nav.PageBounds(0, 10)
	require.Equal(t, 0, start)
	require.Equal(t, 0, end)

	// Single item
	nav.UpdateTotalPages(1, 10)
	start, end = nav.PageBounds(1, 10)
	require.Equal(t, 0, start)
	require.Equal(t, 1, end)

	// Exactly one page
	nav.UpdateTotalPages(10, 10)
	start, end = nav.PageBounds(10, 10)
	require.Equal(t, 0, start)
	require.Equal(t, 10, end)
}

func TestGridNavigator_Lifecycle(t *testing.T) {
	var nav leet.GridNavigator

	// Start with no data
	require.Equal(t, 0, nav.TotalPages())
	require.Equal(t, 0, nav.CurrentPage())

	// Add initial data
	nav.UpdateTotalPages(50, 10) // 5 pages
	require.Equal(t, 5, nav.TotalPages())

	// Navigate through pages
	for i := 1; i < 5; i++ {
		nav.Navigate(1)
		require.Equal(t, i, nav.CurrentPage())
	}

	// Wrap around
	nav.Navigate(1)
	require.Equal(t, 0, nav.CurrentPage())

	// Add more data while on page 0
	nav.UpdateTotalPages(100, 10) // 10 pages
	require.Equal(t, 10, nav.TotalPages())
	require.Equal(t, 0, nav.CurrentPage()) // Should stay on valid page

	// Navigate to last page
	for range 9 {
		nav.Navigate(1)
	}
	require.Equal(t, 9, nav.CurrentPage())

	// Reduce data significantly
	nav.UpdateTotalPages(15, 10) // 2 pages
	require.Equal(t, 2, nav.TotalPages())
	require.Equal(t, 1, nav.CurrentPage()) // Clamped from 9 to 1
}
