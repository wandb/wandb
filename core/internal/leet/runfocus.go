package leet

// runFocusRegion identifies a focusable UI region in the single-run view.
//
// This mirrors the workspace's focusRegion enum but only covers the two
// regions available in single-run mode: the overview sidebar and the
// console logs bottom bar.
type runFocusRegion int

const (
	runFocusOverview runFocusRegion = iota
	runFocusLogs
)

// runFocusOrder defines the Tab-cycling order across single-run regions.
var runFocusOrder = []runFocusRegion{runFocusOverview, runFocusLogs}

// currentRunFocusRegion returns which focusable region currently holds focus.
func (r *Run) currentRunFocusRegion() runFocusRegion {
	if r.bottomBar.Active() {
		return runFocusLogs
	}
	return runFocusOverview
}

// runRegionAvailability returns which focus regions are currently usable.
func (r *Run) runRegionAvailability() map[runFocusRegion]bool {
	firstSec, _ := r.leftSidebar.focusableSectionBounds()
	return map[runFocusRegion]bool{
		runFocusOverview: r.leftSidebar.animState.IsExpanded() && firstSec != -1,
		runFocusLogs:     r.bottomBar.IsExpanded(),
	}
}

// resolveRunFocusAfterVisibilityChange ensures focus stays on a valid region
// after a panel visibility change.
//
// The caller passes the post-toggle visibility for each region. If the
// currently focused region will remain available, focus is left unchanged.
// Otherwise it advances to the next available region. When nothing is
// available, all focus is cleared.
func (r *Run) resolveRunFocusAfterVisibilityChange(overviewVisible, logsVisible bool) {
	cur := r.currentRunFocusRegion()

	// Build the future availability map from the post-toggle state.
	firstSec, _ := r.leftSidebar.focusableSectionBounds()
	avail := map[runFocusRegion]bool{
		runFocusOverview: overviewVisible && firstSec != -1,
		runFocusLogs:     logsVisible,
	}

	if avail[cur] {
		return
	}

	// Current region is being collapsed — find the next available one.
	curIdx := 0
	for i, v := range runFocusOrder {
		if v == cur {
			curIdx = i
			break
		}
	}

	n := len(runFocusOrder)
	for step := 1; step <= n; step++ {
		next := runFocusOrder[(curIdx+step)%n]
		if avail[next] {
			r.setRunFocusRegion(next, 1)
			return
		}
	}

	// Nothing available — clear all focus.
	r.clearAllRunFocus()
}

// cycleRunFocusRegion moves focus to the next available region in the given
// direction, wrapping around the focus order.
func (r *Run) cycleRunFocusRegion(cur runFocusRegion, direction int) {
	avail := r.runRegionAvailability()

	curIdx := 0
	for i, v := range runFocusOrder {
		if v == cur {
			curIdx = i
			break
		}
	}

	n := len(runFocusOrder)
	for step := 1; step <= n; step++ {
		nextIdx := ((curIdx+direction*step)%n + n) % n
		next := runFocusOrder[nextIdx]
		if avail[next] {
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
		r.bottomBar.SetActive(true)
	}
}

// clearAllRunFocus removes focus from all regions.
func (r *Run) clearAllRunFocus() {
	r.bottomBar.SetActive(false)
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
