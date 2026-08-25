package leet

import (
	"fmt"

	tea "charm.land/bubbletea/v2"

	"github.com/wandb/wandb/core/internal/observability"
)

// Mouse-drag pane resizing.
//
// A left-click exactly on a sidebar's border column or on the separator row
// above a stacked pane latches a drag. Mouse motion resizes the pane live;
// release persists the new proportion (a fraction of the terminal dimension)
// to the per-view LayoutOverrides in wandb-leet.json. The "0" key resets a
// view's overrides to the golden-ratio defaults.
//
// The run and workspace views share this state machine through paneDragger;
// each view wires in its own config accessors and re-layout hook.

// dragBoundary identifies a draggable layout boundary.
type dragBoundary int

const (
	dragBoundaryNone dragBoundary = iota
	dragBoundaryLeftSidebar
	dragBoundaryRightSidebar
	dragBoundarySeparator
	dragBoundaryOverviewSection
)

// layoutDrag tracks an in-progress boundary drag.
//
// overrides accumulates the view's pending layout fractions as the mouse
// moves (a separator drag between two fixed panes updates two of them) and
// is persisted once on mouse release. section is set for stack separator
// drags; overview names the latched rule's neighbor sections for run
// overview section drags.
type layoutDrag struct {
	boundary  dragBoundary
	section   stackSectionID
	overview  overviewSeparator
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

// dragTargets describes which boundaries are draggable for one mouse event:
// the terminal size, whether each sidebar is stably expanded (a drag never
// fights an animation), and whether the media pane is fullscreen (which
// hides the separators).
type dragTargets struct {
	width, height               int
	leftExpanded, rightExpanded bool
	mediaFullscreen             bool

	// overview is the view's run overview sidebar when it is stably
	// expanded; the rules between its sections are then draggable.
	overview *RunOverviewSidebar
}

// paneDragger owns mouse-drag pane resizing for one view.
//
// saved/persist read and write the view's LayoutOverrides in the config;
// relayout re-derives the view's pane extents (the view's applyLayoutConfig,
// which reads live overrides back through overrides()).
type paneDragger struct {
	drag layoutDrag

	saved    func() LayoutOverrides
	persist  func(LayoutOverrides) error
	relayout func()
	logger   *observability.CoreLogger
}

// overrides returns the live pane proportions: the in-progress drag's
// pending values, or the persisted config.
func (d *paneDragger) overrides() LayoutOverrides {
	if d.drag.active() {
		return d.drag.overrides
	}
	return d.saved()
}

// handleMouse processes a mouse event for pane-boundary resizing. It returns
// true when the event was consumed by an active or new drag.
func (d *paneDragger) handleMouse(msg tea.MouseMsg, layout Layout, t dragTargets) bool {
	switch m := msg.(type) {
	case tea.MouseClickMsg:
		if m.Button != tea.MouseLeft {
			return false
		}
		drag, ok := boundaryAt(m.X, m.Y, layout, t)
		if !ok || (drag.boundary == dragBoundarySeparator && t.mediaFullscreen) {
			// A stale latch survives when the matching release never
			// reached this view (help overlay, view switch); any new
			// press that misses a boundary clears it.
			d.drag = layoutDrag{}
			return false
		}
		drag.overrides = d.saved()
		d.drag = drag
		return true

	case tea.MouseMotionMsg:
		if !d.drag.active() || m.Button != tea.MouseLeft {
			return false
		}
		d.apply(m.X, m.Y, layout, t)
		return true

	case tea.MouseReleaseMsg:
		if !d.drag.active() {
			return false
		}
		// Legacy X10 mouse encoding reports every release as MouseNone.
		if m.Button != tea.MouseLeft && m.Button != tea.MouseNone {
			return false
		}
		d.finish()
		return true
	}
	return false
}

// apply updates the pending overrides from the mouse position and re-lays
// the view out from them. Sidebar drags are clamped so the main content
// column keeps its minimum width against the opposite sidebar.
func (d *paneDragger) apply(x, y int, layout Layout, t dragTargets) {
	o := &d.drag.overrides
	switch d.drag.boundary {
	case dragBoundaryLeftSidebar:
		maxW := t.width - layout.rightSidebarWidth - mainDragMinWidth
		if maxW < sidebarDragMinWidth {
			return // No legal width at this terminal size.
		}
		w := clamp(x+1, sidebarDragMinWidth, maxW)
		o.LeftSidebar = float64(w) / float64(t.width)
	case dragBoundaryRightSidebar:
		maxW := t.width - layout.leftSidebarWidth - mainDragMinWidth
		if maxW < sidebarDragMinWidth {
			return // No legal width at this terminal size.
		}
		w := clamp(t.width-x, sidebarDragMinWidth, maxW)
		o.RightSidebar = float64(w) / float64(t.width)
	case dragBoundarySeparator:
		if t.mediaFullscreen {
			return // Fullscreen entered mid-drag hides the stack.
		}
		if !dragSeparator(o, layout, d.drag.section, y, t.height) {
			return
		}
	case dragBoundaryOverviewSection:
		if t.overview == nil || !dragOverviewSection(o, t.overview, d.drag.overview, y) {
			return
		}
	}
	// Live values obey the same bounds as the persisted config, so the
	// layout cannot snap when the drag is released and re-derived.
	normalizeLayoutOverrides(o)
	d.drag.dirty = true
	if d.drag.boundary == dragBoundaryOverviewSection {
		// Only the sidebar consumes the overview shares, and it re-reads
		// them on its next render; skip the full pane relayout.
		return
	}
	d.relayout()
}

// finish persists the dragged proportions and ends the drag.
func (d *paneDragger) finish() {
	drag := d.drag
	d.drag = layoutDrag{}
	if !drag.dirty {
		return // Click without motion: nothing changed.
	}
	if err := d.persist(drag.overrides); err != nil {
		d.logger.Error(fmt.Sprintf("leet: failed to save layout: %v", err))
	}
}

// reset restores and persists the view's default pane proportions,
// cancelling any in-flight drag so its release cannot overwrite the reset.
func (d *paneDragger) reset() {
	d.drag = layoutDrag{}
	if err := d.persist(LayoutOverrides{}); err != nil {
		d.logger.Error(fmt.Sprintf("leet: failed to save layout: %v", err))
	}
	d.relayout()
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

// sidebarGrabTolerance widens each sidebar border's mouse target to the
// adjacent column on either side. Terminals report cell-quantized mouse
// coordinates, so a one-column target makes grabbing the border a matter
// of sub-cell luck.
const sidebarGrabTolerance = 1

// nearColumn reports whether x is within sidebarGrabTolerance of col.
func nearColumn(x, col int) bool {
	d := x - col
	return -sidebarGrabTolerance <= d && d <= sidebarGrabTolerance
}

// boundaryAt hit-tests a mouse position against the draggable boundaries:
// the sidebars' border columns (with one column of tolerance either side),
// the separator rules between run overview sections, and the separator rows
// of the central stack.
//
// Sidebar borders are only draggable when the sidebar is stably expanded so
// a drag never fights an animation.
func boundaryAt(x, y int, layout Layout, t dragTargets) (layoutDrag, bool) {
	if y >= layout.totalContentAreaHeight {
		return layoutDrag{}, false
	}

	if layout.leftSidebarWidth > 0 && t.leftExpanded &&
		nearColumn(x, layout.leftSidebarWidth-1) {
		return layoutDrag{boundary: dragBoundaryLeftSidebar}, true
	}
	if layout.rightSidebarWidth > 0 && t.rightExpanded &&
		nearColumn(x, t.width-layout.rightSidebarWidth) {
		return layoutDrag{boundary: dragBoundaryRightSidebar}, true
	}

	if t.overview != nil {
		if drag, ok := overviewBoundaryAt(x, y, layout, t); ok {
			return drag, true
		}
	}

	// Separator rows span the central column only.
	if x < layout.leftSidebarWidth || x >= t.width-layout.rightSidebarWidth {
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

// overviewBoundaryAt hit-tests a mouse position against the separator rules
// between the run overview sidebar's sections, as recorded by the sidebar's
// last render.
func overviewBoundaryAt(x, y int, layout Layout, t dragTargets) (layoutDrag, bool) {
	switch t.overview.side {
	case SidebarSideLeft:
		if x >= layout.leftSidebarWidth {
			return layoutDrag{}, false
		}
	case SidebarSideRight:
		if x < t.width-layout.rightSidebarWidth {
			return layoutDrag{}, false
		}
	default:
		return layoutDrag{}, false
	}

	for _, sep := range t.overview.separators {
		if sep.row == y {
			return layoutDrag{boundary: dragBoundaryOverviewSection, overview: sep}, true
		}
	}
	return layoutDrag{}, false
}

// dragOverviewSection records in o the section shares for dragging the run
// overview rule between latched's neighbor sections to row y. Like
// dragSeparator, it re-reads the live geometry on every motion event, so a
// mid-drag data update cannot leave the drag working against stale rows.
//
// The two neighbors trade rows within the total they currently hold, each
// keeping at least the minimum height and at most the rows its items can
// fill. Every visible section's share is recorded so the allocator
// reproduces exactly these heights. It reports whether o was updated.
func dragOverviewSection(
	o *LayoutOverrides,
	s *RunOverviewSidebar,
	latched overviewSeparator,
	y int,
) bool {
	row := -1
	for _, sep := range s.separators {
		if sep.above == latched.above && sep.below == latched.below {
			row = sep.row
			break
		}
	}
	if row < 0 {
		return false // A neighbor emptied mid-drag; nothing to trade.
	}

	needs := s.sectionNeeds()
	area := s.sectionsArea(needs)
	if area <= 0 {
		return false
	}

	aboveH := s.sections[latched.above].Height
	total := aboveH + s.sections[latched.below].Height
	lo := max(sectionMinHeight, total-needs[latched.below])
	hi := min(needs[latched.above], total-sectionMinHeight)
	if lo > hi {
		return false
	}
	aboveH = clamp(aboveH+y-row, lo, hi)

	for i := range s.sections {
		if h := s.sections[i].Height; h > 0 {
			o.setOverviewFraction(i, float64(h)/float64(area))
		}
	}
	o.setOverviewFraction(latched.above, float64(aboveH)/float64(area))
	o.setOverviewFraction(latched.below, float64(total-aboveH)/float64(area))
	return true
}

// dragSeparator records in o the pane fractions for dragging the separator
// above section to row y, clamped so both neighbors keep their minimum
// heights. It reports whether o was updated.
//
// The pane below the separator keeps its bottom anchored. When the pane
// above is another fixed pane, its fraction is updated too so the boundary
// lands exactly on the mouse row; when it is the flex metrics section, the
// flex absorbs the change instead.
func dragSeparator(
	o *LayoutOverrides,
	layout Layout,
	section stackSectionID,
	y, terminalHeight int,
) bool {
	sections := stackGeometry(layout)
	for i := 1; i < len(sections); i++ {
		if sections[i].id != section {
			continue
		}
		prev, sec := sections[i-1], sections[i]
		bottom := sec.y + sec.h
		lo, hi := prev.y+prev.minH, bottom-1-sec.minH
		if lo > hi {
			return false
		}
		y = clamp(y, lo, hi)

		o.setSection(sec.id, float64(bottom-y-1)/float64(terminalHeight))
		if prev.id != stackSectionMetrics {
			o.setSection(prev.id, float64(y-prev.y)/float64(terminalHeight))
		}
		return true
	}
	return false
}
