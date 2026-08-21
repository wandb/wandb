package leet

import (
	"strings"
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

// testDragTargets returns drag targets for testRunLayout's terminal with
// both sidebars stably expanded.
func testDragTargets() dragTargets {
	return dragTargets{width: 200, leftExpanded: true, rightExpanded: true}
}

func TestBoundaryAtSidebarBorders(t *testing.T) {
	layout := testRunLayout()
	targets := testDragTargets()
	width := targets.width

	// The left sidebar's border is its last column; the border column and
	// one column either side latch (mouse coordinates are cell-quantized,
	// so a one-column target is luck-based).
	for _, x := range []int{38, 39, 40} {
		drag, ok := boundaryAt(x, 5, layout, targets)
		require.True(t, ok, "x=%d", x)
		require.Equal(t, dragBoundaryLeftSidebar, drag.boundary)
	}

	// The right sidebar's border is its first column, same tolerance.
	for _, x := range []int{width - 61, width - 60, width - 59} {
		drag, ok := boundaryAt(x, 5, layout, targets)
		require.True(t, ok, "x=%d", x)
		require.Equal(t, dragBoundaryRightSidebar, drag.boundary)
	}

	// Two columns off is a miss.
	_, ok := boundaryAt(37, 5, layout, targets)
	require.False(t, ok)
	_, ok = boundaryAt(width-58, 5, layout, targets)
	require.False(t, ok)

	// A collapsed/animating sidebar is not draggable.
	collapsed := targets
	collapsed.leftExpanded = false
	_, ok = boundaryAt(39, 5, layout, collapsed)
	require.False(t, ok)

	// The status bar area is off limits.
	_, ok = boundaryAt(39, layout.totalContentAreaHeight, layout, targets)
	require.False(t, ok)
}

func TestBoundaryAtStackSeparators(t *testing.T) {
	layout := testRunLayout()
	targets := testDragTargets()
	width := targets.width

	// Separator above media.
	drag, ok := boundaryAt(100, layout.mediaY-1, layout, targets)
	require.True(t, ok)
	require.Equal(t, dragBoundarySeparator, drag.boundary)
	require.Equal(t, stackSectionMedia, drag.section)

	// Separator above console logs.
	drag, ok = boundaryAt(100, layout.consoleLogsY-1, layout, targets)
	require.True(t, ok)
	require.Equal(t, dragBoundarySeparator, drag.boundary)
	require.Equal(t, stackSectionConsoleLogs, drag.section)

	// Separator rows are only draggable within the central column.
	_, ok = boundaryAt(10, layout.mediaY-1, layout, targets)
	require.False(t, ok)
	_, ok = boundaryAt(width-30, layout.mediaY-1, layout, targets)
	require.False(t, ok)

	// Non-separator rows in the central column are misses.
	_, ok = boundaryAt(100, layout.mediaY, layout, targets)
	require.False(t, ok)
}

func TestBoundaryAtOverviewSeparators(t *testing.T) {
	layout := testRunLayout()
	targets := testDragTargets()

	sb := testOverviewSidebar(t, SidebarSideLeft, layout.leftSidebarWidth)
	view := sb.View(layout.totalContentAreaHeight)
	seps := sb.sectionSeparators()
	require.Len(t, seps, 2)
	targets.overview = sb

	// The derived separator rows match the rendered rule rows.
	var ruleRows []int
	for row, line := range strings.Split(view.Content, "\n") {
		if strings.Contains(line, "————") {
			ruleRows = append(ruleRows, row)
		}
	}
	require.Equal(t, []int{seps[0].row, seps[1].row}, ruleRows)

	// A click on a separator rule inside the sidebar latches a section drag.
	for _, sep := range seps {
		drag, ok := boundaryAt(5, sep.row, layout, targets)
		require.True(t, ok, "row=%d", sep.row)
		require.Equal(t, dragBoundaryOverviewSection, drag.boundary)
		require.Equal(t, sep.above, drag.overview.above)
		require.Equal(t, sep.below, drag.overview.below)
		require.Equal(t, sep.row, drag.overview.baseY)
	}

	// One row off is a miss.
	_, ok := boundaryAt(5, seps[0].row+1, layout, targets)
	require.False(t, ok)

	// The same row outside the sidebar is not an overview drag.
	drag, ok := boundaryAt(100, seps[0].row, layout, targets)
	require.True(t, !ok || drag.boundary != dragBoundaryOverviewSection)

	// No latch without the sidebar (collapsed or animating).
	targets.overview = nil
	_, ok = boundaryAt(5, seps[0].row, layout, targets)
	require.False(t, ok)
}

func TestDragOverviewSectionTradesRows(t *testing.T) {
	ov := overviewSectionDrag{
		above: 0, below: 1,
		baseY:  10,
		aboveH: 5, belowH: 7,
		aboveNeed: 20, belowNeed: 20,
		area: 30,
	}

	// Dragging down by 3 rows grows the section above and shrinks the one
	// below; both shares are fractions of the section area.
	var o LayoutOverrides
	require.True(t, dragOverviewSection(&o, ov, 13))
	require.InDelta(t, 8.0/30, o.OverviewEnv, 1e-9)
	require.InDelta(t, 4.0/30, o.OverviewConfig, 1e-9)

	// Dragging far up stops at the minimum height for the section above.
	o = LayoutOverrides{}
	require.True(t, dragOverviewSection(&o, ov, 0))
	require.InDelta(t, 2.0/30, o.OverviewEnv, 1e-9)
	require.InDelta(t, 10.0/30, o.OverviewConfig, 1e-9)

	// Dragging far down stops where the section above meets its need.
	o = LayoutOverrides{}
	ov.aboveNeed = 6
	require.True(t, dragOverviewSection(&o, ov, 25))
	require.InDelta(t, 6.0/30, o.OverviewEnv, 1e-9)
	require.InDelta(t, 6.0/30, o.OverviewConfig, 1e-9)

	// No legal position: nothing recorded.
	o = LayoutOverrides{}
	ov = overviewSectionDrag{
		above: 0, below: 1,
		baseY:  10,
		aboveH: 2, belowH: 3,
		aboveNeed: 2, belowNeed: 2,
		area: 30,
	}
	require.False(t, dragOverviewSection(&o, ov, 11))
	require.Zero(t, o.OverviewEnv)
	require.Zero(t, o.OverviewConfig)
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
