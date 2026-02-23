package leet

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
)

const (
	systemMetricsPaneContentPadding = 1
	systemMetricsPaneBorderLines    = 1
	systemMetricsPaneHeaderLines    = 1
	systemMetricsPaneMinHeight      = systemMetricsPaneBorderLines + systemMetricsPaneHeaderLines + 1
)

var (
	systemMetricsPaneStyle = lipgloss.NewStyle().
				PaddingLeft(systemMetricsPaneContentPadding)

	systemMetricsPaneBorderStyle = lipgloss.NewStyle().
					Border(topOnlyBorder).
					BorderForeground(colorLayout).
					BorderTop(true).
					BorderBottom(false).
					BorderLeft(false).
					BorderRight(false)
)

// SystemMetricsPane is a collapsible, animated pane intended for rendering
// system metrics in the workspace view.
type SystemMetricsPane struct {
	animState *AnimatedValue
}

func NewSystemMetricsPane() *SystemMetricsPane {
	return &SystemMetricsPane{
		animState: NewAnimatedValue(false, systemMetricsPaneMinHeight),
	}
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
//
// width is the full available width for the pane.
// runLabel is shown in the header (and may be empty).
// grid is the active SystemMetricsGrid to render.
// hint is shown when grid is nil or empty.
func (p *SystemMetricsPane) View(
	width int, runLabel string, grid *SystemMetricsGrid, hint string) string {
	height := p.Height()
	if width <= 0 || height < systemMetricsPaneMinHeight {
		return ""
	}

	contentWidth := max(width-systemMetricsPaneContentPadding, 0)
	contentHeight := max(height-systemMetricsPaneBorderLines, 0)
	gridHeight := max(contentHeight-systemMetricsPaneHeaderLines, 0)

	header := p.renderHeader(contentWidth, runLabel, grid)
	body := header

	if gridHeight > 0 {
		body = lipgloss.JoinVertical(
			lipgloss.Left,
			header,
			p.renderGrid(contentWidth, gridHeight, grid, hint),
		)
	}

	paneContent := systemMetricsPaneStyle.
		Width(contentWidth).
		Height(contentHeight).
		Render(body)

	return systemMetricsPaneBorderStyle.
		Width(width).
		Height(contentHeight).
		Render(paneContent)
}

func (p *SystemMetricsPane) renderHeader(
	contentWidth int, runLabel string, grid *SystemMetricsGrid) string {
	title := headerStyle.Render("System Metrics")
	navInfo := navInfoStyle.Render(p.buildNavigationInfo(grid))

	left := title
	if runLabel != "" {
		sep := " • "
		maxRunWidth := contentWidth - lipgloss.Width(title) - lipgloss.Width(navInfo) - len(sep)
		if maxRunWidth > 0 {
			left = lipgloss.JoinHorizontal(
				lipgloss.Left,
				title,
				navInfoStyle.Render(sep+truncateValue(runLabel, maxRunWidth)),
			)
		}
	}

	fillerWidth := contentWidth - lipgloss.Width(left) - lipgloss.Width(navInfo)
	filler := strings.Repeat(" ", max(fillerWidth, 0))
	return lipgloss.JoinHorizontal(lipgloss.Left, left, filler, navInfo)
}

func (p *SystemMetricsPane) renderGrid(
	contentWidth, gridHeight int, grid *SystemMetricsGrid, hint string) string {
	if hint == "" {
		hint = "No system metrics."
	}

	if grid == nil || grid.ChartCount() == 0 {
		return lipgloss.Place(
			contentWidth,
			gridHeight,
			lipgloss.Left,
			lipgloss.Top,
			navInfoStyle.Render(hint),
		)
	}

	grid.Resize(contentWidth, gridHeight)
	return grid.View()
}

func (p *SystemMetricsPane) buildNavigationInfo(grid *SystemMetricsGrid) string {
	if grid == nil {
		return ""
	}
	chartCount := grid.ChartCount()
	if chartCount == 0 {
		return ""
	}

	size := grid.effectiveGridSize()
	itemsPerPage := ItemsPerPage(size)
	start, end := grid.nav.PageBounds(chartCount, itemsPerPage)
	start++ // Convert to 1-indexed.

	return fmt.Sprintf(" [%d-%d of %d]", start, end, chartCount)
}
