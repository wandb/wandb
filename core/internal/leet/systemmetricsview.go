package leet

import (
	"fmt"
	"strings"

	"charm.land/lipgloss/v2"
)

// renderSystemMetricsHeader renders the shared header used by both the
// workspace system metrics pane and the standalone SYMON view.
//
// The left side shows the title and optional run label. The right side shows
// the current chart pagination state.
func renderSystemMetricsHeader(
	contentWidth int,
	titleText string,
	runLabel string,
	grid *SystemMetricsGrid,
) string {
	title := headerStyle.Render(titleText)
	navInfo := navInfoStyle.Render(buildSystemMetricsNavigationInfo(grid))

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

// renderSystemMetricsBody renders either an informative empty state or the
// system metrics chart grid itself.
func renderSystemMetricsBody(
	contentWidth, gridHeight int,
	grid *SystemMetricsGrid,
	emptyHint string,
	noMatchHint string,
) string {
	if emptyHint == "" {
		emptyHint = "No system metrics."
	}
	if noMatchHint == "" {
		noMatchHint = "No matching system metrics."
	}

	if grid == nil || grid.ChartCount() == 0 {
		return lipgloss.Place(
			contentWidth,
			gridHeight,
			lipgloss.Left,
			lipgloss.Top,
			navInfoStyle.Render(emptyHint),
		)
	}

	if grid.FilterQuery() != "" && grid.FilteredChartCount() == 0 {
		return lipgloss.Place(
			contentWidth,
			gridHeight,
			lipgloss.Left,
			lipgloss.Top,
			navInfoStyle.Render(noMatchHint),
		)
	}

	grid.Resize(contentWidth, gridHeight)
	return grid.View()
}

// buildSystemMetricsNavigationInfo reports the visible chart range for the
// current page.
func buildSystemMetricsNavigationInfo(grid *SystemMetricsGrid) string {
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
	if itemsPerPage <= 0 {
		return ""
	}
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
