package leet

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"
)

// SidebarState represents the UI state of a sidebar.
type SidebarState int

const (
	SidebarCollapsed SidebarState = iota
	SidebarExpanded
	SidebarCollapsing
	SidebarExpanding
)

// AnimationState manages sidebar animation state.
type AnimationState struct {
	state         SidebarState
	currentWidth  int
	targetWidth   int
	expandedWidth int
	timer         time.Time
}

func NewAnimationState(expanded bool, expandedWidth int) *AnimationState {
	state := SidebarCollapsed
	currentWidth := 0
	targetWidth := 0

	if expanded {
		state = SidebarExpanded
		currentWidth = expandedWidth
		targetWidth = expandedWidth
	}

	return &AnimationState{
		state:         state,
		currentWidth:  currentWidth,
		targetWidth:   targetWidth,
		expandedWidth: expandedWidth,
	}
}

// Toggle toggles between expanded and collapsed states.
func (a *AnimationState) Toggle() {
	switch a.state {
	case SidebarCollapsed:
		a.state = SidebarExpanding
		a.targetWidth = a.expandedWidth
		a.timer = time.Now()
	case SidebarExpanded:
		a.state = SidebarCollapsing
		a.targetWidth = 0
		a.timer = time.Now()
	}
}

// Update updates the animation state and returns a command if animation continues.
func (a *AnimationState) Update() (tea.Cmd, bool) {
	if a.state != SidebarExpanding && a.state != SidebarCollapsing {
		return nil, false
	}

	elapsed := time.Since(a.timer)
	progress := float64(elapsed) / float64(AnimationDuration)

	if progress >= 1.0 {
		a.currentWidth = a.targetWidth
		if a.state == SidebarExpanding {
			a.state = SidebarExpanded
		} else {
			a.state = SidebarCollapsed
		}
		return nil, true
	}

	if a.state == SidebarExpanding {
		a.currentWidth = int(easeOutCubic(progress) * float64(a.expandedWidth))
	} else {
		a.currentWidth = int((1 - easeOutCubic(progress)) * float64(a.expandedWidth))
	}

	return a.animationCmd(), false
}

// SetExpandedWidth updates the expanded width.
func (a *AnimationState) SetExpandedWidth(width int) {
	a.expandedWidth = width
	if a.state == SidebarExpanded {
		a.targetWidth = width
		a.currentWidth = width
	}
}

// Width returns the current width.
func (a *AnimationState) Width() int {
	return a.currentWidth
}

// State returns the current state.
func (a *AnimationState) State() SidebarState {
	return a.state
}

// IsVisible returns whether the sidebar is visible.
func (a *AnimationState) IsVisible() bool {
	return a.state != SidebarCollapsed
}

// IsAnimating returns whether the sidebar is currently animating.
func (a *AnimationState) IsAnimating() bool {
	return a.state == SidebarExpanding || a.state == SidebarCollapsing
}

// easeOutCubic provides smooth deceleration for animations.
func easeOutCubic(t float64) float64 {
	t--
	return t*t*t + 1
}

// animationCmd returns a command to continue the animation.
func (a *AnimationState) animationCmd() tea.Cmd {
	return tea.Tick(time.Millisecond*16, func(t time.Time) tea.Msg {
		return LeftSidebarAnimationMsg{}
	})
}
