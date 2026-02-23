package leet

import (
	"sync"
	"time"
)

// AnimatedValue manages a scalar (width, height, etc.) that animates
// smoothly between a collapsed state (0) and an expanded state.
type AnimatedValue struct {
	mu sync.RWMutex

	// current is the current rendered size (px/cols/rows).
	current int

	// target is the desired size we're animating toward.
	target int

	// expanded is the fully-expanded size.
	expanded int

	// startTime indicates when the current animation started.
	startTime time.Time
}

func NewAnimatedValue(isExpanded bool, expandedSize int) *AnimatedValue {
	a := &AnimatedValue{expanded: expandedSize}
	if isExpanded {
		a.current = expandedSize
		a.target = expandedSize
	}
	return a
}

// Toggle toggles between expanded and collapsed targets.
//
// No-op while animating to match current model gating semantics.
func (a *AnimatedValue) Toggle() {
	a.mu.Lock()
	defer a.mu.Unlock()

	a.startTime = time.Now()

	if a.target == 0 {
		a.target = a.expanded
	} else {
		a.target = 0
	}
}

// Update advances the animation given a wall-clock time and returns
// whether the animation is complete.
func (a *AnimatedValue) Update(now time.Time) bool {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.current == a.target {
		return true
	}
	elapsed := now.Sub(a.startTime)
	progress := float64(elapsed) / float64(AnimationDuration)
	if progress >= 1 {
		a.current = a.target
		a.startTime = time.Time{}
		return true
	}

	if a.current < a.target {
		a.current = int(easeOutCubic(progress) * float64(a.expanded))
	} else {
		a.current = int((1 - easeOutCubic(progress)) * float64(a.expanded))
	}

	return false
}

// SetExpanded updates the desired expanded size.
func (a *AnimatedValue) SetExpanded(size int) {
	a.mu.Lock()
	defer a.mu.Unlock()

	wasExpanded := a.target > 0 && a.current == a.target

	a.expanded = size
	if a.target > 0 {
		a.target = size
	}
	if wasExpanded {
		// We were stably expanded; snap immediately to the new size.
		a.current = size
	}
}

// Value returns the current animated value.
func (a *AnimatedValue) Value() int {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.current
}

// IsAnimating reports whether the value is in motion.
func (a *AnimatedValue) IsAnimating() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.current != a.target
}

// IsVisible returns true if the value is greater than zero.
func (a *AnimatedValue) IsVisible() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.current > 0
}

// IsExpanded returns true if we're stably at the expanded value.
func (a *AnimatedValue) IsExpanded() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.target > 0 && (a.current == a.target)
}

// IsCollapsed returns true if we're stably at zero.
func (a *AnimatedValue) IsCollapsed() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.target == 0 && a.current == 0
}

// IsExpanding reports whether we're animating toward the expanded value.
func (a *AnimatedValue) IsExpanding() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.current < a.target
}

// IsCollapsing reports whether we're animating toward zero.
func (a *AnimatedValue) IsCollapsing() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.current > a.target
}

// ForceCollapse immediately snaps to zero without animation.
func (a *AnimatedValue) ForceCollapse() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.current = 0
	a.target = 0
	a.startTime = time.Time{}
}

// ForceExpand immediately snaps to the expanded value without animation.
//
// Intended for tests that need to skip animation.
func (a *AnimatedValue) ForceExpand() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.current = a.expanded
	a.target = a.expanded
	a.startTime = time.Time{}
}

// easeOutCubic maps t ∈ [0, 1] -> [0, 1] with deceleration near the end.
//
// Values outside [0,1] are acceptable; callers clamp at 1.
func easeOutCubic(t float64) float64 {
	// (t-1)^3 + 1
	return (t-1)*(t-1)*(t-1) + 1
}
