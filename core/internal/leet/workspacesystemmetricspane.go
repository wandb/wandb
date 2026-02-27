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
	systemMetricsPaneMinHeight      = systemMetricsPaneBorderLines +
		systemMetricsPaneHeaderLines +
		MinMetricChartHeight + ChartBorderSize + ChartTitleHeight

	WorkspaceSystemMetricsPaneHeader = "System Metrics"
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
func (p *SystemMetricsPane) View(
	width int, runLabel string, grid *SystemMetricsGrid, hint string) string {
	height := p.Height()
	if width <= 0 || height < systemMetricsPaneMinHeight {
		return ""
	}

	innerW := max(width-systemMetricsPaneContentPadding, 0)
	innerH := max(height-systemMetricsPaneBorderLines, 0)
	gridH := max(innerH-systemMetricsPaneHeaderLines, 0)

	header := p.renderHeader(innerW, runLabel, grid)
	body := header
	if gridH > 0 {
		body = lipgloss.JoinVertical(
			lipgloss.Left,
			header,
			p.renderGrid(innerW, gridH, grid, hint),
		)
	}

	// Render into the unpadded content area first, then apply padding and border.
	body = lipgloss.Place(innerW, innerH, lipgloss.Left, lipgloss.Top, body)
	padded := systemMetricsPaneStyle.Render(body)
	bordered := systemMetricsPaneBorderStyle.Render(padded)

	return lipgloss.Place(width, height, lipgloss.Left, lipgloss.Top, bordered)
}

func (p *SystemMetricsPane) renderHeader(
	contentWidth int, runLabel string, grid *SystemMetricsGrid) string {
	title := headerStyle.Render(WorkspaceSystemMetricsPaneHeader)
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

	if grid.FilterQuery() != "" && grid.FilteredChartCount() == 0 {
		return lipgloss.Place(
			contentWidth,
			gridHeight,
			lipgloss.Left,
			lipgloss.Top,
			navInfoStyle.Render("No matching system metrics."),
		)
	}

	grid.Resize(contentWidth, gridHeight)
	return grid.View()
}

func (p *SystemMetricsPane) buildNavigationInfo(grid *SystemMetricsGrid) string {
	if grid == nil {
		return ""
	}
	totalCount := grid.ChartCount()
	filteredCount := grid.FilteredChartCount()
	if totalCount == 0 || filteredCount == 0 {
		return ""
	}

	size := grid.effectiveGridSize()
	itemsPerPage := ItemsPerPage(size)
	start, end := grid.nav.PageBounds(filteredCount, itemsPerPage)
	start++ // Convert to 1-indexed.

	if filteredCount != totalCount {
		return fmt.Sprintf(
			" [%d-%d of %d filtered from %d total]",
			start,
			end,
			filteredCount,
			totalCount,
		)
	}

	return fmt.Sprintf(" [%d-%d of %d]", start, end, filteredCount)
}
