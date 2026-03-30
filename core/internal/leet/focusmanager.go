package leet

// FocusTarget identifies a focusable UI region.
type FocusTarget int

const (
	FocusTargetNone FocusTarget = iota
	FocusTargetRunsList
	FocusTargetOverview
	FocusTargetMetricsGrid
	FocusTargetSystemMetrics
	FocusTargetMedia
	FocusTargetConsoleLogs
)

// FocusRegionDef defines a focusable region with availability and activation hooks.
type FocusRegionDef struct {
	Target     FocusTarget
	Available  func() bool
	Activate   func(direction int)
	Deactivate func()
}

// FocusManager is the single source of truth for which UI component holds focus.
//
// It tracks one FocusTarget at a time, supports Tab cycling through available
// regions, and resolves focus after visibility changes. All focus state changes
// flow through this manager.
type FocusManager struct {
	current FocusTarget
	regions []FocusRegionDef
}

// NewFocusManager creates a FocusManager with the given region definitions.
// The regions slice defines the Tab-cycling order.
func NewFocusManager(regions []FocusRegionDef) *FocusManager {
	return &FocusManager{
		current: FocusTargetNone,
		regions: regions,
	}
}

// Current returns the currently focused target.
func (fm *FocusManager) Current() FocusTarget { return fm.current }

// IsTarget returns true if t is the currently focused target.
func (fm *FocusManager) IsTarget(t FocusTarget) bool { return fm.current == t }

// SetTarget deactivates all regions and activates the given target.
// direction is +1 (forward/Tab) or -1 (backward/Shift+Tab) and is passed
// to the Activate callback so components like overview sidebar can focus
// their first or last section.
func (fm *FocusManager) SetTarget(t FocusTarget, direction int) {
	fm.deactivateAll()
	for i := range fm.regions {
		if fm.regions[i].Target == t {
			fm.current = t
			fm.regions[i].Activate(direction)
			return
		}
	}
	fm.current = FocusTargetNone
}

// ClearAll deactivates all regions and sets focus to none.
func (fm *FocusManager) ClearAll() {
	fm.deactivateAll()
	fm.current = FocusTargetNone
}

// Tab cycles focus to the next available region in the given direction.
// direction is +1 for Tab and -1 for Shift+Tab.
func (fm *FocusManager) Tab(direction int) {
	n := len(fm.regions)
	if n == 0 {
		return
	}

	curIdx := fm.indexOf(fm.current)
	if curIdx == -1 {
		if direction >= 0 {
			curIdx = -1
		} else {
			curIdx = 0
		}
	}

	for step := 1; step <= n; step++ {
		nextIdx := ((curIdx+direction*step)%n + n) % n
		r := &fm.regions[nextIdx]
		if r.Available() {
			fm.deactivateAll()
			fm.current = r.Target
			r.Activate(direction)
			return
		}
	}
}

// TabWithinOrAdvance tries the withinFn first (e.g., cycling overview sections).
// If withinFn returns true, the key was handled within the current region.
// Otherwise, it advances to the next region via Tab.
func (fm *FocusManager) TabWithinOrAdvance(direction int, withinFn func(int) bool) {
	if withinFn != nil && withinFn(direction) {
		return
	}
	fm.Tab(direction)
}

// ResolveAfterVisibilityChange checks if the current target is still available.
// If not, it advances to the first available region. If none are available,
// it clears all focus.
func (fm *FocusManager) ResolveAfterVisibilityChange() {
	if fm.current == FocusTargetNone {
		return
	}

	// Check if current is still available.
	for i := range fm.regions {
		if fm.regions[i].Target == fm.current {
			if fm.regions[i].Available() {
				return
			}
			break
		}
	}

	// Current is no longer available. Find the first available region.
	for i := range fm.regions {
		if fm.regions[i].Available() {
			fm.deactivateAll()
			fm.current = fm.regions[i].Target
			fm.regions[i].Activate(1)
			return
		}
	}

	fm.ClearAll()
}

func (fm *FocusManager) deactivateAll() {
	for i := range fm.regions {
		fm.regions[i].Deactivate()
	}
}

func (fm *FocusManager) indexOf(t FocusTarget) int {
	for i := range fm.regions {
		if fm.regions[i].Target == t {
			return i
		}
	}
	return -1
}
