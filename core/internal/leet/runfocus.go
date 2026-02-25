package leet

// runFocusRegion identifies a focusable UI region in the single-run view.
//
// This mirrors the workspace's focusRegion enum but only covers the two
// regions available in single-run mode: the overview sidebar and the
// console logs bottom bar.
type runFocusRegion int

const (
	runFocusNone runFocusRegion = iota
	runFocusOverview
	runFocusLogs
)

// runFocusOrder defines the Tab-cycling order across single-run regions.
var runFocusOrder = []runFocusRegion{runFocusOverview, runFocusLogs}

// currentRunFocusRegion returns which focusable region currently holds focus.
func (r *Run) currentRunFocusRegion() runFocusRegion {
	switch {
	case r.consoleLogsPane.Active():
		return runFocusLogs
	case r.leftSidebar.hasActiveSection():
		return runFocusOverview
	default:
		return runFocusNone
	}
}

// runRegionAvailability returns which regions are currently focusable.
func (r *Run) runRegionAvailability() (overview, logs bool) {
	firstSec, _ := r.leftSidebar.focusableSectionBounds()
	overview = r.leftSidebar.animState.IsExpanded() && firstSec != -1
	logs = r.consoleLogsPane.IsExpanded()
	return overview, logs
}

func runFocusRegionAvailable(region runFocusRegion, overviewAvail, logsAvail bool) bool {
	switch region {
	case runFocusOverview:
		return overviewAvail
	case runFocusLogs:
		return logsAvail
	default:
		return false
	}
}

func indexRunFocusRegion(order []runFocusRegion, region runFocusRegion) int {
	for i, v := range order {
		if v == region {
			return i
		}
	}
	return -1
}

// resolveRunFocusAfterVisibilityChange ensures focus stays on a valid region
// after a panel visibility change. It mirrors Workspace.resolveFocusAfterVisibilityChange
// but is specialized for the single-run view (overview + logs).
func (r *Run) resolveRunFocusAfterVisibilityChange(overviewVisible, logsVisible bool) {
	cur := r.currentRunFocusRegion()

	firstSec, _ := r.leftSidebar.focusableSectionBounds()
	overviewAvail := overviewVisible && firstSec != -1
	logsAvail := logsVisible
	if runFocusRegionAvailable(cur, overviewAvail, logsAvail) {
		return
	}

	n := len(runFocusOrder)
	if n == 0 {
		r.clearAllRunFocus()
		return
	}

	// If nothing is focused, start from the beginning of the focus order.
	// Using -1 means step=1 evaluates index 0 first.
	curIdx := indexRunFocusRegion(runFocusOrder, cur)

	// Current region is being collapsed — find the next available one.
	for step := 1; step <= n; step++ {
		next := runFocusOrder[(curIdx+step)%n]
		if runFocusRegionAvailable(next, overviewAvail, logsAvail) {
			r.setRunFocusRegion(next, 1)
			return
		}
	}

	// Nothing available — clear focus.
	r.clearAllRunFocus()
}

// cycleRunFocusRegion cycles focus among available regions in the given direction.
func (r *Run) cycleRunFocusRegion(cur runFocusRegion, direction int) {
	overviewAvail, logsAvail := r.runRegionAvailability()

	// Find current index in order.
	n := len(runFocusOrder)
	if n == 0 {
		return
	}

	curIdx := indexRunFocusRegion(runFocusOrder, cur)
	if curIdx == -1 {
		// With no current focus, Tab should pick the first available region and
		// Shift-Tab should pick the last.
		if direction >= 0 {
			curIdx = -1
		} else {
			curIdx = 0
		}
	}

	// Attempt each region in order.
	for step := 1; step <= n; step++ {
		nextIdx := curIdx + direction*step
		nextIdx = ((nextIdx % n) + n) % n
		next := runFocusOrder[nextIdx]
		if runFocusRegionAvailable(next, overviewAvail, logsAvail) {
			r.setRunFocusRegion(next, direction)
			return
		}
	}
}

// setRunFocusRegion clears all focus and activates the given region.
func (r *Run) setRunFocusRegion(region runFocusRegion, direction int) {
	r.clearAllRunFocus()

	switch region {
	case runFocusOverview:
		firstSec, lastSec := r.leftSidebar.focusableSectionBounds()
		if direction >= 0 {
			r.leftSidebar.setActiveSection(firstSec)
		} else {
			r.leftSidebar.setActiveSection(lastSec)
		}
	case runFocusLogs:
		r.consoleLogsPane.SetActive(true)
	}
}

// clearAllRunFocus removes focus from all regions.
func (r *Run) clearAllRunFocus() {
	r.consoleLogsPane.SetActive(false)
	r.leftSidebar.deactivateAllSections()
}

// cycleRunOverviewSection tries to move within overview sections.
//
// Returns true if the navigation was handled (i.e. we're not at a boundary).
func (r *Run) cycleRunOverviewSection(direction int) bool {
	firstSec, lastSec := r.leftSidebar.focusableSectionBounds()
	if !r.leftSidebar.animState.IsExpanded() || firstSec == -1 {
		return false
	}

	atBoundary := (direction == 1 && r.leftSidebar.activeSection == lastSec) ||
		(direction == -1 && r.leftSidebar.activeSection == firstSec)
	if atBoundary {
		return false
	}

	r.leftSidebar.navigateSection(direction)
	return true
}
