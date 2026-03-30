package leet

import (
	"time"

	"charm.land/lipgloss/v2"
)

const (
	systemMetricsPaneContentPadding = 1
	systemMetricsPaneHeaderLines    = 1
	systemMetricsPaneMinHeight      = systemMetricsPaneHeaderLines +
		MinMetricChartHeight + ChartBorderSize + ChartTitleHeight

	WorkspaceSystemMetricsPaneHeader = "System Metrics"
)

var (
	systemMetricsPaneStyle = lipgloss.NewStyle().
		PaddingLeft(systemMetricsPaneContentPadding)
)

// SystemMetricsPane is a collapsible, animated pane intended for rendering
// system metrics in the workspace view.
type SystemMetricsPane struct {
	animState *AnimatedValue
}

func NewSystemMetricsPane(animState *AnimatedValue) *SystemMetricsPane {
	return &SystemMetricsPane{animState: animState}
}

func (p *SystemMetricsPane) Height() int             { return p.animState.Value() }
func (p *SystemMetricsPane) IsExpanded() bool        { return p.animState.IsExpanded() }
func (p *SystemMetricsPane) IsVisible() bool         { return p.animState.IsVisible() }
func (p *SystemMetricsPane) IsAnimating() bool       { return p.animState.IsAnimating() }
func (p *SystemMetricsPane) Toggle()                 { p.animState.Toggle() }
func (p *SystemMetricsPane) Update(t time.Time) bool { return p.animState.Update(t) }

func (p *SystemMetricsPane) SetExpandedHeight(height int) {
	p.animState.SetExpanded(max(height, systemMetricsPaneMinHeight))
}

// View renders the system metrics pane.
func (p *SystemMetricsPane) View(
	width int, runLabel string, grid *SystemMetricsGrid, hint string) string {
	height := p.Height()
	if width <= 0 || height < systemMetricsPaneMinHeight {
		return ""
	}

	innerW := max(width-systemMetricsPaneContentPadding, 0)
	innerH := max(height, 0)
	gridH := max(innerH-systemMetricsPaneHeaderLines, 0)

	header := renderSystemMetricsHeader(
		innerW, WorkspaceSystemMetricsPaneHeader, runLabel, grid)
	body := header
	if gridH > 0 {
		body = lipgloss.JoinVertical(
			lipgloss.Left,
			header,
			renderSystemMetricsBody(
				innerW, gridH, grid, hint, "No matching system metrics."),
		)
	}

	// Render into the unpadded content area first, then apply padding and border.
	body = lipgloss.Place(innerW, innerH, lipgloss.Left, lipgloss.Top, body)
	padded := systemMetricsPaneStyle.Render(body)

	return lipgloss.Place(width, height, lipgloss.Left, lipgloss.Top, padded)
}
