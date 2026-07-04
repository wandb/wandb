package leet

import (
	"testing"

	"github.com/stretchr/testify/require"
)

// testRunLayout mirrors a single-run view: metrics (flex) on top, media and
// console logs stacked below, one separator row above each fixed pane.
//
//	y 0..29  metrics (30)
//	y 30     separator
//	y 31..50 media (20)
//	y 51     separator
//	y 52..61 logs (10)
func testRunLayout() Layout {
	return Layout{
		leftSidebarWidth:       40,
		mainContentAreaWidth:   100,
		rightSidebarWidth:      60,
		totalContentAreaHeight: 62,
		height:                 30,
		mediaY:                 31,
		mediaHeight:            20,
		consoleLogsY:           52,
		consoleLogsHeight:      10,
	}
}

func TestBoundaryAtSidebarBorders(t *testing.T) {
	layout := testRunLayout()
	const width = 200

	// Left sidebar border column is the sidebar's last column.
	drag, ok := boundaryAt(39, 5, width, layout, true, true)
	require.True(t, ok)
	require.Equal(t, dragBoundaryLeftSidebar, drag.boundary)

	// Right sidebar border column is its first column.
	drag, ok = boundaryAt(width-60, 5, width, layout, true, true)
	require.True(t, ok)
	require.Equal(t, dragBoundaryRightSidebar, drag.boundary)

	// One column off is a miss.
	_, ok = boundaryAt(38, 5, width, layout, true, true)
	require.False(t, ok)
	_, ok = boundaryAt(width-59, 5, width, layout, true, true)
	require.False(t, ok)

	// A collapsed/animating sidebar is not draggable.
	_, ok = boundaryAt(39, 5, width, layout, false, true)
	require.False(t, ok)

	// The status bar area is off limits.
	_, ok = boundaryAt(39, layout.totalContentAreaHeight, width, layout, true, true)
	require.False(t, ok)
}

func TestBoundaryAtStackSeparators(t *testing.T) {
	layout := testRunLayout()
	const width = 200

	// Separator above media.
	drag, ok := boundaryAt(100, layout.mediaY-1, width, layout, true, true)
	require.True(t, ok)
	require.Equal(t, dragBoundarySeparator, drag.boundary)
	require.Equal(t, stackSectionMedia, drag.section)

	// Separator above console logs.
	drag, ok = boundaryAt(100, layout.consoleLogsY-1, width, layout, true, true)
	require.True(t, ok)
	require.Equal(t, dragBoundarySeparator, drag.boundary)
	require.Equal(t, stackSectionConsoleLogs, drag.section)

	// Separator rows are only draggable within the central column.
	_, ok = boundaryAt(10, layout.mediaY-1, width, layout, true, true)
	require.False(t, ok)
	_, ok = boundaryAt(width-30, layout.mediaY-1, width, layout, true, true)
	require.False(t, ok)

	// Non-separator rows in the central column are misses.
	_, ok = boundaryAt(100, layout.mediaY, width, layout, true, true)
	require.False(t, ok)
}

func TestDragSeparatorHeightTracksMouse(t *testing.T) {
	layout := testRunLayout()
	const termH = 63 // content + status bar

	// Dragging the media separator up by 5 rows grows media by 5.
	newH, frac, ok := dragSeparatorHeight(layout, stackSectionMedia, layout.mediaY-1-5, termH)
	require.True(t, ok)
	require.Equal(t, layout.mediaHeight+5, newH)
	require.InDelta(t, float64(newH)/float64(termH), frac, 1e-9)

	// Dragging down by 5 shrinks media by 5.
	newH, _, ok = dragSeparatorHeight(layout, stackSectionMedia, layout.mediaY-1+5, termH)
	require.True(t, ok)
	require.Equal(t, layout.mediaHeight-5, newH)
}

func TestDragSeparatorHeightClamps(t *testing.T) {
	layout := testRunLayout()
	const termH = 63

	// Dragging far down clamps at the pane's min height.
	newH, _, ok := dragSeparatorHeight(layout, stackSectionMedia, 1000, termH)
	require.True(t, ok)
	require.Equal(t, mediaPaneMinHeight, newH)

	// Dragging far up clamps so the section above keeps its min height.
	newH, _, ok = dragSeparatorHeight(layout, stackSectionMedia, 0, termH)
	require.True(t, ok)
	mediaBottom := layout.mediaY + layout.mediaHeight
	require.Equal(t, mediaBottom-minFlexMetricsHeight-1, newH)

	// Unknown or top-most sections are not draggable.
	_, _, ok = dragSeparatorHeight(layout, stackSectionMetrics, 10, termH)
	require.False(t, ok)
	_, _, ok = dragSeparatorHeight(layout, stackSectionSystemMetrics, 10, termH)
	require.False(t, ok)
}

func TestSidebarWidthFor(t *testing.T) {
	// No override: golden-ratio default.
	require.Equal(t, expandedSidebarWidth(200, false), sidebarWidthFor(200, 0, false))
	require.Equal(t, expandedSidebarWidth(200, true), sidebarWidthFor(200, 0, true))

	// Override fraction of terminal width.
	require.Equal(t, 50, sidebarWidthFor(200, 0.25, false))

	// Overrides can go below the default minimum, but not the drag minimum.
	require.Equal(t, sidebarDragMinWidth, sidebarWidthFor(200, 0.05, false))

	// The main content column keeps its minimum width.
	require.Equal(t, 200-mainDragMinWidth, sidebarWidthFor(200, 0.99, false))
}

func TestPaneHeightFor(t *testing.T) {
	require.Equal(t, 17, paneHeightFor(0, 60, 17))
	require.Equal(t, 30, paneHeightFor(0.5, 60, 17))
}
