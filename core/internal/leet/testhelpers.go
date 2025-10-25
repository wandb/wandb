// TestAPI provides a controlled interface for testing internal model state.
// These methods are only exposed for tests in the leet_test package.
package leet

// TestLeftSidebarVisible returns true if the left sidebar is visible
func (m *Model) TestLeftSidebarVisible() bool {
	// TODO
	return true
}

// TestSeriesCount returns the number of series in the chart
func (c *TimeSeriesLineChart) TestSeriesCount() int {
	return len(c.series)
}

// CurrentPage returns the current grid of charts.
func (g *SystemMetricsGrid) CurrentPage() [][]*TimeSeriesLineChart {
	return g.currentPage
}
