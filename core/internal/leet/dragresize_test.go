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

// frac converts a pane extent to its terminal-dimension fraction.
func frac(size, terminalSize int) float64 {
	return float64(size) / float64(terminalSize)
}

func TestDragSeparatorBelowFlexResizesOnePane(t *testing.T) {
	layout := testRunLayout()
	const termH = 63 // content + status bar

	// The pane above the media separator is the flex metrics grid, so only
	// media resizes; dragging up by 5 rows grows it by 5.
	var o LayoutOverrides
	require.True(t, dragSeparator(&o, layout, stackSectionMedia, layout.mediaY-1-5, termH))
	require.Equal(t, LayoutOverrides{Media: frac(layout.mediaHeight+5, termH)}, o)

	// Dragging down by 5 shrinks media by 5.
	o = LayoutOverrides{}
	require.True(t, dragSeparator(&o, layout, stackSectionMedia, layout.mediaY-1+5, termH))
	require.Equal(t, LayoutOverrides{Media: frac(layout.mediaHeight-5, termH)}, o)
}

func TestDragSeparatorBetweenFixedPanesResizesBoth(t *testing.T) {
	layout := testRunLayout()
	const termH = 63

	// Media (fixed) sits above the console logs separator: dragging down by
	// 3 rows grows media by 3 and shrinks logs by 3.
	var o LayoutOverrides
	require.True(t,
		dragSeparator(&o, layout, stackSectionConsoleLogs, layout.consoleLogsY-1+3, termH))
	require.Equal(t, LayoutOverrides{
		Media: frac(layout.mediaHeight+3, termH),
		Logs:  frac(layout.consoleLogsHeight-3, termH),
	}, o)
}

func TestDragSeparatorClamps(t *testing.T) {
	layout := testRunLayout()
	const termH = 63

	// Dragging far down clamps at the pane's min height.
	var o LayoutOverrides
	require.True(t, dragSeparator(&o, layout, stackSectionMedia, 1000, termH))
	require.Equal(t, LayoutOverrides{Media: frac(mediaPaneMinHeight, termH)}, o)

	// Dragging far up clamps so the section above keeps its min height.
	o = LayoutOverrides{}
	require.True(t, dragSeparator(&o, layout, stackSectionMedia, 0, termH))
	mediaBottom := layout.mediaY + layout.mediaHeight
	require.Equal(t,
		LayoutOverrides{Media: frac(mediaBottom-minFlexMetricsHeight-1, termH)}, o)

	// Unknown or top-most sections are not draggable.
	o = LayoutOverrides{}
	require.False(t, dragSeparator(&o, layout, stackSectionMetrics, 10, termH))
	require.False(t, dragSeparator(&o, layout, stackSectionSystemMetrics, 10, termH))
	require.Equal(t, LayoutOverrides{}, o)
}
