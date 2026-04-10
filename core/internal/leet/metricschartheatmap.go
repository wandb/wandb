package leet

import (
	"fmt"
	"image/color"
	"math"

	"charm.land/lipgloss/v2/compat"
)

// metricsChartWrapper adds heatmap toggle capability to an EpochLineChart.
//
// It embeds the line chart so all existing methods work through delegation.
// When heatmapMode is true, View/Draw/inspection methods switch to the
// companion FrenchFriesChart.
type metricsChartWrapper struct {
	*EpochLineChart
	heatmap     *FrenchFriesChart
	heatmapMode bool
}

func newMetricsChartWrapper(
	line *EpochLineChart,
	colors []compat.AdaptiveColor,
) *metricsChartWrapper {
	w := &metricsChartWrapper{EpochLineChart: line}
	heatmap := NewFrenchFriesChart(&FrenchFriesChartParams{
		Width:         parkedCanvasSize,
		Height:        parkedCanvasSize,
		Title:         line.Title(),
		XLabelFunc:    formatStepLabel,
		SeriesColorFn: w.seriesColor,
		Colors:        colors,
	})
	w.heatmap = heatmap
	return w
}

// seriesColor returns the foreground color assigned to a series, or nil.
func (w *metricsChartWrapper) seriesColor(seriesName string) color.Color {
	style := w.SeriesStyle(seriesName)
	if style == nil {
		return nil
	}
	return style.GetForeground()
}

// AddData feeds both the line chart and the heatmap companion.
func (w *metricsChartWrapper) AddData(key string, data MetricData) {
	w.EpochLineChart.AddData(key, data)
	for i := range data.X {
		w.heatmap.AddDataPoint(key, data.X[i], data.Y[i])
	}
}

// PromoteSeriesToTop pins the series to the top row in the heatmap
// and draws it last (on top) in the line chart.
func (w *metricsChartWrapper) PromoteSeriesToTop(key string) {
	w.EpochLineChart.PromoteSeriesToTop(key)
	w.heatmap.SetPinnedSeries(key)
}

// RemoveSeries removes the series from both charts.
func (w *metricsChartWrapper) RemoveSeries(key string) {
	w.EpochLineChart.RemoveSeries(key)
	w.heatmap.RemoveSeries(key)
}

// View returns the active chart's rendered view.
func (w *metricsChartWrapper) View() string {
	if w.heatmapMode {
		w.syncViewWindow()
		w.heatmap.DrawIfNeeded()
		return w.heatmap.View()
	}
	return w.EpochLineChart.View()
}

// Resize updates both charts.
func (w *metricsChartWrapper) Resize(width, height int) {
	w.EpochLineChart.Resize(width, height)
	w.heatmap.Resize(width, height)
}

// Draw draws the active chart.
func (w *metricsChartWrapper) Draw() {
	if w.heatmapMode {
		w.syncViewWindow()
		w.heatmap.DrawIfNeeded()
		return
	}
	w.EpochLineChart.Draw()
}

// DrawIfNeeded draws the active chart if dirty.
func (w *metricsChartWrapper) DrawIfNeeded() {
	if w.heatmapMode {
		w.syncViewWindow()
		w.heatmap.DrawIfNeeded()
		return
	}
	w.EpochLineChart.DrawIfNeeded()
}

// Park reduces the embedded line chart's canvas to save memory.
func (w *metricsChartWrapper) Park() {
	w.EpochLineChart.Park()
}

// HandleZoom forwards to the line chart (it owns the X domain) and syncs.
func (w *metricsChartWrapper) HandleZoom(direction string, mouseX int) {
	w.EpochLineChart.HandleZoom(direction, mouseX)
	if w.heatmapMode {
		w.syncViewWindow()
		w.heatmap.DrawIfNeeded()
	}
}

// ToggleYScale is a no-op in heatmap mode.
func (w *metricsChartWrapper) ToggleYScale() bool {
	if w.heatmapMode {
		return false
	}
	return w.EpochLineChart.ToggleYScale()
}

// IsLogY returns false in heatmap mode.
func (w *metricsChartWrapper) IsLogY() bool {
	if w.heatmapMode {
		return false
	}
	return w.EpochLineChart.IsLogY()
}

// ScaleLabel returns the active display mode label.
func (w *metricsChartWrapper) ScaleLabel() string {
	if w.heatmapMode {
		return "heatmap"
	}
	return w.EpochLineChart.ScaleLabel()
}

// SupportsHeatmap returns true — all metrics charts support it.
func (w *metricsChartWrapper) SupportsHeatmap() bool { return true }

// ToggleHeatmapMode switches between line and heatmap rendering.
func (w *metricsChartWrapper) ToggleHeatmapMode() bool {
	w.heatmapMode = !w.heatmapMode
	if w.heatmapMode {
		w.syncViewWindow()
	}
	return true
}

// IsHeatmapMode reports whether the chart is currently rendering as a heatmap.
func (w *metricsChartWrapper) IsHeatmapMode() bool { return w.heatmapMode }

// GraphWidth returns the graph width of the active chart.
func (w *metricsChartWrapper) GraphWidth() int {
	if w.heatmapMode {
		return w.heatmap.GraphWidth()
	}
	return w.EpochLineChart.GraphWidth()
}

// graphStartX returns the first graph column inside the rendered chart cell.
func (w *metricsChartWrapper) graphStartX() int {
	if w.heatmapMode {
		return w.heatmap.GraphStartX()
	}
	// Line chart: border(1) + Y-axis labels if present.
	startX := 1
	if w.YStep() > 0 {
		startX += w.Origin().X + 1
	}
	return startX
}

// GraphHeight returns the graph height of the active chart.
func (w *metricsChartWrapper) GraphHeight() int {
	if w.heatmapMode {
		return w.heatmap.GraphHeight()
	}
	return w.EpochLineChart.GraphHeight()
}

// StartInspection begins inspection on the active chart.
func (w *metricsChartWrapper) StartInspection(mouseX int) {
	if w.heatmapMode {
		w.heatmap.StartInspectionAt(mouseX, 0)
		return
	}
	w.EpochLineChart.StartInspection(mouseX)
}

// UpdateInspection moves the crosshair on the active chart.
func (w *metricsChartWrapper) UpdateInspection(mouseX int) {
	if w.heatmapMode {
		w.heatmap.UpdateInspectionAt(mouseX, 0)
		return
	}
	w.EpochLineChart.UpdateInspection(mouseX)
}

// EndInspection clears inspection on both charts.
func (w *metricsChartWrapper) EndInspection() {
	w.EpochLineChart.EndInspection()
	w.heatmap.EndInspection()
}

// IsInspecting reports whether the active chart has an inspection overlay.
func (w *metricsChartWrapper) IsInspecting() bool {
	if w.heatmapMode {
		return w.heatmap.IsInspecting()
	}
	return w.EpochLineChart.IsInspecting()
}

// InspectionData returns the active chart's inspection state.
func (w *metricsChartWrapper) InspectionData() (x, y float64, active bool) {
	if w.heatmapMode {
		return w.heatmap.InspectionData()
	}
	return w.EpochLineChart.InspectionData()
}

// InspectAtDataX positions the inspection cursor at a data-space X value.
func (w *metricsChartWrapper) InspectAtDataX(targetX float64) {
	if w.heatmapMode {
		w.syncViewWindow()
		w.heatmap.InspectAtDataX(targetX)
		return
	}
	w.EpochLineChart.InspectAtDataX(targetX)
}

func (w *metricsChartWrapper) syncViewWindow() {
	w.heatmap.SetViewWindow(w.ViewMinX(), w.ViewMaxX())
}

// formatStepLabel formats a step number for the heatmap X-axis.
func formatStepLabel(value float64, maxWidth int) string {
	if !isFinite(value) || maxWidth <= 0 {
		return ""
	}

	v := math.Round(value)
	label := fmt.Sprintf("%.0f", v)
	if len(label) <= maxWidth {
		return label
	}

	// Compact: use k/M suffixes.
	switch {
	case math.Abs(v) >= 1e6:
		label = fmt.Sprintf("%.0fM", v/1e6)
	case math.Abs(v) >= 1e3:
		label = fmt.Sprintf("%.0fk", v/1e3)
	}
	if len(label) <= maxWidth {
		return label
	}
	return TruncateTitle(label, maxWidth)
}
