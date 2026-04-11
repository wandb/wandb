package leet

// systemMetricChart is the minimal surface that SystemMetricsGrid needs
// from a rendered system-metric chart.
type systemMetricChart interface {
	Title() string
	TitleDetail() string
	View() string
	Resize(width, height int)
	DrawIfNeeded()
	Park()
	AddDataPoint(seriesName string, timestamp int64, value float64)
	GraphWidth() int
	GraphHeight() int
	GraphStartX() int
	GraphStartY() int
	HandleZoom(direction string, mouseX int)
	ToggleYScale() bool
	IsLogY() bool
	SupportsHeatmap() bool
	ToggleHeatmapMode() bool
	IsHeatmapMode() bool
	ViewModeLabel() string
	ScaleLabel() string
	StartInspectionAt(mouseX, mouseY int)
	UpdateInspectionAt(mouseX, mouseY int)
	EndInspection()
	IsInspecting() bool
	InspectionData() (x, y float64, active bool)
	InspectAtDataX(targetX float64)
}
