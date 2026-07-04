package leet

import "math"

// Mouse-drag pane resizing.
//
// A left-click exactly on a sidebar's border column or on the separator row
// above a stacked pane latches a drag. Mouse motion resizes the pane live;
// release persists the new proportion (a fraction of the terminal dimension)
// to the per-view LayoutOverrides in wandb-leet.json. The "0" key resets a
// view's overrides to the golden-ratio defaults.

const (
	// sidebarDragMinWidth is the narrowest a sidebar can be dragged to.
	// Deliberately smaller than SidebarMinWidth so users can shrink
	// sidebars below the default clamp.
	sidebarDragMinWidth = 20

	// mainDragMinWidth is the narrowest the main content column can be
	// squeezed to by dragging a sidebar border.
	mainDragMinWidth = 24

	// minFlexMetricsHeight is the shortest the flex metrics section can be
	// squeezed to by dragging the separator below it.
	minFlexMetricsHeight = 5
)

// dragBoundary identifies a draggable layout boundary.
type dragBoundary int

const (
	dragBoundaryNone dragBoundary = iota
	dragBoundaryLeftSidebar
	dragBoundaryRightSidebar
	dragBoundarySeparator
)

// layoutDrag tracks an in-progress boundary drag.
//
// overrides accumulates the view's pending layout fractions as the mouse
// moves (a separator drag between two fixed panes updates two of them) and
// is persisted once on mouse release. section is set for separator drags.
type layoutDrag struct {
	boundary  dragBoundary
	section   stackSectionID
	overrides LayoutOverrides
	dirty     bool
}

func (d layoutDrag) active() bool { return d.boundary != dragBoundaryNone }

// setSection records a stacked pane's height fraction.
func (o *LayoutOverrides) setSection(id stackSectionID, frac float64) {
	switch id {
	case stackSectionSystemMetrics:
		o.System = frac
	case stackSectionMedia:
		o.Media = frac
	case stackSectionConsoleLogs:
		o.Logs = frac
	}
}

// stackGeom describes one visible section of the central vertical stack.
type stackGeom struct {
	id   stackSectionID
	y    int
	h    int
	minH int
}

// stackGeometry returns the visible central-column sections in top-to-bottom
// order. Sections with zero height (hidden, or absent in this view) are
// omitted, so the same code serves both the run and workspace layouts.
func stackGeometry(layout Layout) []stackGeom {
	all := []stackGeom{
		{stackSectionMetrics, 0, layout.height, minFlexMetricsHeight},
		{stackSectionSystemMetrics, layout.systemMetricsY,
			layout.systemMetricsHeight, systemMetricsPaneMinHeight},
		{stackSectionMedia, layout.mediaY, layout.mediaHeight, mediaPaneMinHeight},
		{stackSectionConsoleLogs, layout.consoleLogsY,
			layout.consoleLogsHeight, ConsoleLogsPaneMinHeight},
	}
	visible := all[:0]
	for _, g := range all {
		if g.h > 0 {
			visible = append(visible, g)
		}
	}
	return visible
}

// boundaryAt hit-tests a mouse position against the draggable boundaries:
// the sidebars' border columns and the separator rows of the central stack.
//
// Sidebar borders are only draggable when the sidebar is stably expanded so
// a drag never fights an animation.
func boundaryAt(
	x, y, width int,
	layout Layout,
	leftExpanded, rightExpanded bool,
) (layoutDrag, bool) {
	if y >= layout.totalContentAreaHeight {
		return layoutDrag{}, false
	}

	if layout.leftSidebarWidth > 0 && leftExpanded &&
		x == layout.leftSidebarWidth-1 {
		return layoutDrag{boundary: dragBoundaryLeftSidebar}, true
	}
	if layout.rightSidebarWidth > 0 && rightExpanded &&
		x == width-layout.rightSidebarWidth {
		return layoutDrag{boundary: dragBoundaryRightSidebar}, true
	}

	// Separator rows span the central column only.
	if x < layout.leftSidebarWidth || x >= width-layout.rightSidebarWidth {
		return layoutDrag{}, false
	}
	sections := stackGeometry(layout)
	for i := 1; i < len(sections); i++ {
		if y == sections[i].y-1 {
			return layoutDrag{
				boundary: dragBoundarySeparator,
				section:  sections[i].id,
			}, true
		}
	}
	return layoutDrag{}, false
}

// separatorResize is one pane's new extent produced by a separator drag.
type separatorResize struct {
	section stackSectionID
	height  int
	frac    float64
}

// dragSeparator computes the pane resizes for dragging the separator above
// section to row y. The row is clamped so both neighbors keep their minimum
// heights.
//
// The pane below the separator keeps its bottom anchored. When the pane
// above is another fixed pane, it is resized too so the boundary lands
// exactly on the mouse row; when it is the flex metrics section, the flex
// absorbs the change instead.
func dragSeparator(
	layout Layout,
	section stackSectionID,
	y, terminalHeight int,
) []separatorResize {
	sections := stackGeometry(layout)
	for i := 1; i < len(sections); i++ {
		if sections[i].id != section {
			continue
		}
		prev, sec := sections[i-1], sections[i]
		bottom := sec.y + sec.h
		lo, hi := prev.y+prev.minH, bottom-1-sec.minH
		if lo > hi {
			return nil
		}
		y = clamp(y, lo, hi)

		resizes := []separatorResize{{
			section: sec.id,
			height:  bottom - y - 1,
			frac:    float64(bottom-y-1) / float64(terminalHeight),
		}}
		if prev.id != stackSectionMetrics {
			resizes = append(resizes, separatorResize{
				section: prev.id,
				height:  y - prev.y,
				frac:    float64(y-prev.y) / float64(terminalHeight),
			})
		}
		return resizes
	}
	return nil
}

// paneHeightFor returns a stacked pane's expanded height for the given
// override fraction of the terminal height, or the fallback default when no
// override is set. The pane's own SetExpandedHeight enforces its minimum.
func paneHeightFor(frac float64, terminalHeight, fallback int) int {
	if frac <= 0 {
		return fallback
	}
	return int(math.Round(float64(terminalHeight) * frac))
}

// sidebarWidthFor returns the expanded sidebar width for the given override
// fraction of the terminal width. A zero fraction falls back to the
// golden-ratio default.
func sidebarWidthFor(terminalWidth int, frac float64, oppositeVisible bool) int {
	if frac <= 0 {
		return expandedSidebarWidth(terminalWidth, oppositeVisible)
	}
	maxW := max(terminalWidth-mainDragMinWidth, sidebarDragMinWidth)
	w := int(math.Round(float64(terminalWidth) * frac))
	return clamp(w, sidebarDragMinWidth, maxW)
}
