package tui

import (
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

// Sidebar animation constants
const (
	// Golden ratio: ~1.618, so sidebar takes ~38.2% of width for a 16:10 feel
	SidebarWidthRatio = 0.382
	SidebarMinWidth   = 40
	SidebarMaxWidth   = 80
	AnimationDuration = 150 * time.Millisecond
	AnimationSteps    = 10
)

// RunOverview contains the run information to display
type RunOverview struct {
	RunPath     string
	Config      map[string]any
	Summary     map[string]any
	Environment map[string]string
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

// SidebarStyle defines the visual style for the sidebar
var (
	sidebarStyle = lipgloss.NewStyle().
			Padding(0, 1)

	sidebarBorderStyle = lipgloss.NewStyle().
				Border(lipgloss.Border{
			Top:         "─",
			Bottom:      "",
			Left:        "",
			Right:       "|",
			TopLeft:     "",
			TopRight:    "",
			BottomLeft:  "",
			BottomRight: "",
		}).
		BorderForeground(lipgloss.Color("238"))

	sidebarHeaderStyle = lipgloss.NewStyle().
				Bold(true).
				Foreground(lipgloss.Color("86")).
				MarginBottom(1)

	sidebarSectionStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("245")).
				Bold(true).
				MarginTop(1).
				MarginBottom(2)

	// sidebarKeyStyle = lipgloss.NewStyle().
	// 		Foreground(lipgloss.Color("241"))

	sidebarValueStyle = lipgloss.NewStyle().
				Foreground(lipgloss.Color("252"))
)

// NewSidebar creates a new sidebar instance
func NewSidebar() *Sidebar {
	vp := viewport.New(SidebarMinWidth, 10)
	vp.Style = lipgloss.NewStyle()

	return &Sidebar{
		state:         SidebarCollapsed,
		currentWidth:  0,
		targetWidth:   0,
		expandedWidth: SidebarMinWidth,
		viewport:      vp,
		runOverview:   RunOverview{},
	}
}

// UpdateDimensions updates the sidebar dimensions based on terminal width
func (s *Sidebar) UpdateDimensions(terminalWidth int) {
	// Calculate sidebar width using golden ratio
	calculatedWidth := int(float64(terminalWidth) * SidebarWidthRatio)

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

// SetRunOverview sets the run overview information
func (s *Sidebar) SetRunOverview(overview RunOverview) {
	s.runOverview = overview
	s.updateViewportContent()
}

// updateViewportContent updates the viewport with formatted run overview
func (s *Sidebar) updateViewportContent() {
	var content strings.Builder

	// Run Path
	content.WriteString(sidebarSectionStyle.Render("Run Path"))
	content.WriteString("\n")
	content.WriteString(sidebarValueStyle.Render(s.runOverview.RunPath))
	content.WriteString("\n\n")

	s.viewport.SetContent(content.String())
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
