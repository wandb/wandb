package tui

import (
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// RightSidebar represents a collapsible right sidebar panel.
type RightSidebar struct {
	state          SidebarState
	currentWidth   int
	targetWidth    int
	expandedWidth  int
	animationStep  int
	animationTimer time.Time
}

var (
	rightSidebarStyle       = lipgloss.NewStyle().Padding(0, 1)
	rightSidebarBorderStyle = lipgloss.NewStyle().Border(lipgloss.Border{Left: "│"}).BorderForeground(lipgloss.Color("238"))

	LeftBorder = lipgloss.Border{
		Top:         " ",
		Bottom:      " ",
		Left:        "│",
		Right:       "",
		TopLeft:     "│",
		TopRight:    " ",
		BottomLeft:  "│",
		BottomRight: " ",
	}
)

// NewRightSidebar creates a new right sidebar instance
func NewRightSidebar() *RightSidebar {
	return &RightSidebar{
		state:         SidebarCollapsed,
		currentWidth:  0,
		targetWidth:   0,
		expandedWidth: SidebarMinWidth,
	}
}

// UpdateDimensions updates the right sidebar dimensions based on terminal width and left sidebar state
func (rs *RightSidebar) UpdateDimensions(terminalWidth int, leftSidebarVisible bool) {
	var calculatedWidth int

	if leftSidebarVisible {
		// When both sidebars are visible, use nested golden ratio
		// 0.382 * 0.618 ≈ 0.236
		calculatedWidth = int(float64(terminalWidth) * 0.236)
	} else {
		// When only right sidebar is visible, use standard golden ratio
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatio)
	}

	// Clamp to min/max
	switch {
	case calculatedWidth < SidebarMinWidth:
		rs.expandedWidth = SidebarMinWidth
	case calculatedWidth > SidebarMaxWidth:
		rs.expandedWidth = SidebarMaxWidth
	default:
		rs.expandedWidth = calculatedWidth
	}

	// Update target width if expanded
	if rs.state == SidebarExpanded {
		rs.targetWidth = rs.expandedWidth
		rs.currentWidth = rs.expandedWidth
	}
}

// Toggle toggles the sidebar state between expanded and collapsed
func (rs *RightSidebar) Toggle() {
	switch rs.state {
	case SidebarCollapsed:
		rs.state = SidebarExpanding
		rs.targetWidth = rs.expandedWidth
		rs.animationStep = 0
		rs.animationTimer = time.Now()
	case SidebarExpanded:
		rs.state = SidebarCollapsing
		rs.targetWidth = 0
		rs.animationStep = 0
		rs.animationTimer = time.Now()
	}
}

// Update handles animation updates for the right sidebar
func (rs *RightSidebar) Update(msg tea.Msg) (*RightSidebar, tea.Cmd) {
	var cmds []tea.Cmd

	// Handle animation
	if rs.state == SidebarExpanding || rs.state == SidebarCollapsing {
		elapsed := time.Since(rs.animationTimer)
		progress := float64(elapsed) / float64(AnimationDuration)

		if progress >= 1.0 {
			// Animation complete
			rs.currentWidth = rs.targetWidth
			if rs.state == SidebarExpanding {
				rs.state = SidebarExpanded
			} else {
				rs.state = SidebarCollapsed
			}
		} else {
			// Animate width using easing function
			if rs.state == SidebarExpanding {
				rs.currentWidth = int(easeOutCubic(progress) * float64(rs.expandedWidth))
			} else {
				rs.currentWidth = int((1 - easeOutCubic(progress)) * float64(rs.expandedWidth))
			}

			// Continue animation
			cmds = append(cmds, rs.animationCmd())
		}
	}

	return rs, tea.Batch(cmds...)
}

// View renders the right sidebar
func (rs *RightSidebar) View(height int) string {
	if rs.currentWidth <= 0 {
		return ""
	}

	// Placeholder content for now
	content := lipgloss.NewStyle().
		Foreground(lipgloss.Color("245")).
		Italic(true).
		Render("System Metrics\n(Coming Soon)")

	// Apply styles with exact dimensions
	styledContent := rightSidebarStyle.
		Width(rs.currentWidth-1). // Account for border
		Height(height).
		MaxWidth(rs.currentWidth-1).
		MaxHeight(height).
		Align(lipgloss.Center, lipgloss.Center).
		Render(content)

	// Apply border (only on the left side)
	bordered := rightSidebarBorderStyle.
		Width(rs.currentWidth).
		Height(height).
		MaxWidth(rs.currentWidth).
		MaxHeight(height).
		Render(styledContent)

	return bordered
}

// Width returns the current width of the sidebar
func (rs *RightSidebar) Width() int {
	return rs.currentWidth
}

// IsVisible returns true if the sidebar is visible
func (rs *RightSidebar) IsVisible() bool {
	return rs.state != SidebarCollapsed
}

// IsAnimating returns true if the sidebar is currently animating
func (rs *RightSidebar) IsAnimating() bool {
	return rs.state == SidebarExpanding || rs.state == SidebarCollapsing
}

// animationCmd returns a command to continue the animation
func (rs *RightSidebar) animationCmd() tea.Cmd {
	return tea.Tick(time.Millisecond*16, func(t time.Time) tea.Msg {
		return RightSidebarAnimationMsg{}
	})
}

// RightSidebarAnimationMsg is sent during right sidebar animations
type RightSidebarAnimationMsg struct{}

// UpdateExpandedWidth recalculates the expanded width based on the current terminal width
// and whether the other sidebar is visible. This ensures correct width when toggling.
func (rs *RightSidebar) UpdateExpandedWidth(terminalWidth int, leftSidebarVisible bool) {
	var calculatedWidth int

	if leftSidebarVisible {
		// When both sidebars are visible, use nested golden ratio
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatioBoth)
	} else {
		// When only right sidebar is visible, use standard golden ratio
		calculatedWidth = int(float64(terminalWidth) * SidebarWidthRatio)
	}

	// Clamp to min/max
	switch {
	case calculatedWidth < SidebarMinWidth:
		rs.expandedWidth = SidebarMinWidth
	case calculatedWidth > SidebarMaxWidth:
		rs.expandedWidth = SidebarMaxWidth
	default:
		rs.expandedWidth = calculatedWidth
	}
}
