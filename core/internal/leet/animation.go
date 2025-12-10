package leet

import (
	"sync"
	"time"
)

// AnimationState manages a sidebar's animated width.
type AnimationState struct {
	mu sync.RWMutex

	// currentWidth is the current rendered width (px/cols).
	currentWidth int

	// targetWidth is the desired width we're animating toward.
	targetWidth int

	// expandedWidth is the desired width when expanded.
	expandedWidth int

	// animationStartTime indicates when the current animation started.
	animationStartTime time.Time
}

func NewAnimationState(expanded bool, expandedWidth int) *AnimationState {
	a := &AnimationState{expandedWidth: expandedWidth}
	if expanded {
		a.currentWidth = expandedWidth
		a.targetWidth = expandedWidth
	}
	return a
}

// Toggle toggles between expanded and collapsed targets.
//
// No-op while animating to match current model gating semantics.
func (a *AnimationState) Toggle() {
	a.mu.Lock()
	defer a.mu.Unlock()

	a.animationStartTime = time.Now()

	if a.targetWidth == 0 {
		a.targetWidth = a.expandedWidth
	} else {
		a.targetWidth = 0
	}
}

// Update advances the animation given a wall-clock time and returns
// whether the animation is complete.
func (a *AnimationState) Update(now time.Time) bool {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.currentWidth == a.targetWidth {
		return true
	}
	elapsed := now.Sub(a.animationStartTime)
	progress := float64(elapsed) / float64(AnimationDuration)
	if progress >= 1 {
		a.currentWidth = a.targetWidth
		a.animationStartTime = time.Time{}
		return true
	}

	if a.currentWidth < a.targetWidth {
		a.currentWidth = int(easeOutCubic(progress) * float64(a.expandedWidth))
	} else {
		a.currentWidth = int((1 - easeOutCubic(progress)) * float64(a.expandedWidth))
	}

	return false
}

// SetExpandedWidth updates the desired expanded width.
func (a *AnimationState) SetExpandedWidth(width int) {
	a.mu.Lock()
	defer a.mu.Unlock()

	wasExpanded := a.targetWidth > 0 && a.currentWidth == a.targetWidth

	a.expandedWidth = width
	if a.targetWidth > 0 {
		a.targetWidth = width
	}
	if wasExpanded {
		// We were stably expanded; snap immediately to the new width.
		a.currentWidth = width
	}
}

// Width returns the current width.
func (a *AnimationState) Width() int {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.currentWidth
}

// IsAnimating reports whether currentWidth != targetWidth.
func (a *AnimationState) IsAnimating() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.currentWidth != a.targetWidth
}

// IsVisible returns true if any width is visible on screen.
func (a *AnimationState) IsVisible() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.currentWidth > 0
}

// IsExpanded returns true if we're stably at expanded width.
func (a *AnimationState) IsExpanded() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.targetWidth > 0 && (a.currentWidth == a.targetWidth)
}

// IsCollapsed returns true if we're stably collapsed.
func (a *AnimationState) IsCollapsed() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.targetWidth == 0 && a.currentWidth == 0
}

// IsExpanding/IsCollapsing are derived from the direction to the target.
func (a *AnimationState) IsExpanding() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.currentWidth < a.targetWidth
}
func (a *AnimationState) IsCollapsing() bool {
	a.mu.RLock()
	defer a.mu.RUnlock()
	return a.currentWidth > a.targetWidth
}

// easeOutCubic maps t c [0, 1] -> [0, 1] with deceleration near the end.
//
// Values outside [0,1] are acceptable; callers clamp at 1.
func easeOutCubic(t float64) float64 {
	// (t-1)^3 + 1
	return (t-1)*(t-1)*(t-1) + 1
}
