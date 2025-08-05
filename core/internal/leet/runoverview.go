//go:build !wandb_core

package leet

import (
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// SidebarState represents the state of the sidebar
type SidebarState int

const (
	SidebarCollapsed SidebarState = iota
	SidebarExpanded
	SidebarCollapsing
	SidebarExpanding
)

// RunOverview contains the run information to display
type RunOverview struct {
	RunPath     string
	Project     string
	ID          string
	DisplayName string
	Config      map[string]any
	Summary     map[string]any
	Environment map[string]any
}

// Sidebar represents a collapsible sidebar panel
type Sidebar struct {
	state          SidebarState
	currentWidth   int
	targetWidth    int
	expandedWidth  int // Calculated based on terminal width
	animationStep  int
	animationTimer time.Time
	viewport       viewport.Model
	runOverview    RunOverview
}

// NewSidebar creates a new sidebar instance
func NewSidebar() *Sidebar {
	vp := viewport.New(SidebarMinWidth, 10)
	vp.Style = lipgloss.NewStyle().
		BorderStyle(RightBorder).
		BorderForeground(lipgloss.Color("238"))
	return &Sidebar{
		state:         SidebarCollapsed,
		currentWidth:  0,
		targetWidth:   0,
		expandedWidth: SidebarMinWidth,
		viewport:      vp,
	}
}

// updateViewportContent updates the viewport with formatted run overview
func (s *Sidebar) updateViewportContent() {
	var b strings.Builder

	if s.runOverview.ID != "" {
		b.WriteString(sidebarSectionStyle.Render("ID: "))
		b.WriteString(sidebarValueStyle.Render(s.runOverview.ID))
		b.WriteRune('\n')
	}
	if s.runOverview.DisplayName != "" {
		b.WriteString(sidebarSectionStyle.Render("Name: "))
		b.WriteString(sidebarValueStyle.Render(s.runOverview.DisplayName))
		b.WriteRune('\n')
	}
	if s.runOverview.Project != "" {
		b.WriteString(sidebarSectionStyle.Render("Project: "))
		b.WriteString(sidebarValueStyle.Render(s.runOverview.Project))
		b.WriteRune('\n')
	}

	renderMap(&b, "Config", s.runOverview.Config)
	renderMap(&b, "Summary", s.runOverview.Summary)
	renderMap(&b, "Environment", s.runOverview.Environment)

	s.viewport.SetContent(b.String())
}

// renderMap is a helper to recursively render maps in the sidebar.
func renderMap(b *strings.Builder, title string, data map[string]any) {
	if len(data) == 0 {
		return
	}
	b.WriteRune('\n')
	b.WriteString(sidebarSectionStyle.Render(title))
	b.WriteRune('\n')
	writeSortedMap(b, data, 0)
}

// writeSortedMap recursively writes map content, sorted by key, with indentation.
func writeSortedMap(b *strings.Builder, m map[string]any, indent int) {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	indentStr := strings.Repeat("  ", indent)
	for _, k := range keys {
		v := m[k]
		keyStr := sidebarKeyStyle.Render(fmt.Sprintf("%s%s:", indentStr, k))
		if subMap, ok := v.(map[string]any); ok {
			b.WriteString(keyStr)
			b.WriteRune('\n')
			writeSortedMap(b, subMap, indent+1)
		} else {
			valStr := sidebarValueStyle.Render(fmt.Sprintf("%v", v))
			b.WriteString(fmt.Sprintf("%s %s\n", keyStr, valStr))
		}
	}
}

// SetRunOverview sets the run overview information and triggers a content update.
func (s *Sidebar) SetRunOverview(overview RunOverview) {
	s.runOverview = overview
	s.updateViewportContent()
}

// UpdateDimensions updates the sidebar dimensions based on terminal width
func (s *Sidebar) UpdateDimensions(terminalWidth int, rightSidebarVisible bool) {
	var calculatedWidth int

	if rightSidebarVisible {
		// When both sidebars are visible, use nested golden ratio
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatioBoth)
	} else {
		// When only left sidebar is visible, use standard golden ratio
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatio)
	}

	// Clamp to min/max
	switch {
	case calculatedWidth < SidebarMinWidth:
		s.expandedWidth = SidebarMinWidth
	case calculatedWidth > SidebarMaxWidth:
		s.expandedWidth = SidebarMaxWidth
	default:
		s.expandedWidth = calculatedWidth
	}

	// Update target width if expanded
	if s.state == SidebarExpanded {
		s.targetWidth = s.expandedWidth
		s.currentWidth = s.expandedWidth
	}
}

// Toggle toggles the sidebar state between expanded and collapsed
func (s *Sidebar) Toggle() {
	switch s.state {
	case SidebarCollapsed:
		s.state = SidebarExpanding
		s.targetWidth = s.expandedWidth
		s.animationStep = 0
		s.animationTimer = time.Now()
	case SidebarExpanded:
		s.state = SidebarCollapsing
		s.targetWidth = 0
		s.animationStep = 0
		s.animationTimer = time.Now()
	}
}

// Update handles animation updates for the sidebar
func (s *Sidebar) Update(msg tea.Msg) (*Sidebar, tea.Cmd) {
	var cmd tea.Cmd
	var cmds []tea.Cmd

	// Only update viewport for relevant messages (not page navigation)
	switch msg := msg.(type) {
	case tea.MouseMsg:
		if msg.X < s.currentWidth {
			s.viewport, cmd = s.viewport.Update(msg)
			cmds = append(cmds, cmd)
		}
	case tea.KeyMsg:
		// Only handle viewport-specific keys
		switch msg.String() {
		case "up", "down", "home", "end":
			if s.state == SidebarExpanded {
				s.viewport, cmd = s.viewport.Update(msg)
				cmds = append(cmds, cmd)
			}
		}
	}

	// Handle animation
	if s.state == SidebarExpanding || s.state == SidebarCollapsing {
		elapsed := time.Since(s.animationTimer)
		progress := float64(elapsed) / float64(AnimationDuration)

		if progress >= 1.0 {
			// Animation complete
			s.currentWidth = s.targetWidth
			if s.state == SidebarExpanding {
				s.state = SidebarExpanded
			} else {
				s.state = SidebarCollapsed
			}
		} else {
			// Animate width using easing function
			if s.state == SidebarExpanding {
				s.currentWidth = int(easeOutCubic(progress) * float64(s.expandedWidth))
			} else {
				s.currentWidth = int((1 - easeOutCubic(progress)) * float64(s.expandedWidth))
			}

			// Continue animation
			cmds = append(cmds, s.animationCmd())
		}
	}

	return s, tea.Batch(cmds...)
}

// View renders the sidebar
func (s *Sidebar) View(height int) string {
	if s.currentWidth <= 0 {
		return ""
	}

	// Update viewport dimensions
	s.viewport.Width = s.currentWidth - 3 // Account for padding and border
	s.viewport.Height = height - 3        // Account for header and padding

	// Build sidebar content
	header := sidebarHeaderStyle.Render("Run Overview")

	// Render viewport with current content
	viewportContent := s.viewport.View()

	// Combine header and viewport
	content := lipgloss.JoinVertical(
		lipgloss.Left,
		header,
		viewportContent,
	)

	// Apply styles with exact dimensions
	styledContent := sidebarStyle.
		Width(s.currentWidth - 1). // Account for border
		Height(height).
		MaxWidth(s.currentWidth - 1).
		MaxHeight(height).
		Render(content)

	// Apply border (only on the right side)
	bordered := sidebarBorderStyle.
		Width(s.currentWidth).
		Height(height).
		MaxWidth(s.currentWidth).
		MaxHeight(height).
		Render(styledContent)

	return bordered
}

// Width returns the current width of the sidebar
func (s *Sidebar) Width() int {
	return s.currentWidth
}

// IsVisible returns true if the sidebar is visible
func (s *Sidebar) IsVisible() bool {
	return s.state != SidebarCollapsed
}

// IsAnimating returns true if the sidebar is currently animating
func (s *Sidebar) IsAnimating() bool {
	return s.state == SidebarExpanding || s.state == SidebarCollapsing
}

// animationCmd returns a command to continue the animation
func (s *Sidebar) animationCmd() tea.Cmd {
	return tea.Tick(time.Millisecond*16, func(t time.Time) tea.Msg { // ~60fps
		return SidebarAnimationMsg{}
	})
}

// easeOutCubic provides smooth deceleration for animations
func easeOutCubic(t float64) float64 {
	t--
	return t*t*t + 1
}

// SidebarAnimationMsg is sent during sidebar animations
type SidebarAnimationMsg struct{}
