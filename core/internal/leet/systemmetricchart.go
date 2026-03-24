package leet

// systemMetricChart is the minimal surface that SystemMetricsGrid needs
// from a rendered system-metric chart.
type systemMetricChart interface {
	Title() string
	TitleDetail() string
	View() string
	Resize(width, height int)
	DrawIfNeeded()
	AddDataPoint(seriesName string, timestamp int64, value float64)
	GraphWidth() int
	GraphStartX() int
	HandleZoom(direction string, mouseX int)
	ToggleYScale() bool
	IsLogY() bool
	ViewModeLabel() string
	ScaleLabel() string
	StartInspection(mouseX int)
	UpdateInspection(mouseX int)
	EndInspection()
	IsInspecting() bool
	InspectionData() (x, y float64, active bool)
	InspectAtDataX(targetX float64)
}
