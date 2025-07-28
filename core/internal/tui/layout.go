package tui

import "github.com/charmbracelet/lipgloss"

// Layout constants
const (
	GridRows        = 3
	GridCols        = 5
	ChartsPerPage   = GridRows * GridCols
	StatusBarHeight = 1
	MinChartWidth   = 20
	MinChartHeight  = 5
)

// Styles
var (
	borderStyle = lipgloss.NewStyle().
			BorderStyle(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("238")) // dark gray

	titleStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("250")). // light gray
			Bold(true)

	focusedBorderStyle = borderStyle.BorderForeground(lipgloss.Color("4"))

	pageInfoStyle = lipgloss.NewStyle().
			Foreground(lipgloss.AdaptiveColor{Light: "#000000", Dark: "#FFFFFF"}).
			Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#0C8599"}).
			Padding(0, 1)

	statusBarStyle = lipgloss.NewStyle().
			Foreground(lipgloss.AdaptiveColor{Light: "#FFFFFF", Dark: "#FFFFFF"}).
			Background(lipgloss.AdaptiveColor{Light: "#45B7D1", Dark: "#1864AB"})
)

// ChartDimensions calculates chart dimensions for the given window size
type ChartDimensions struct {
	ChartWidth             int
	ChartHeight            int
	ChartWidthWithPadding  int
	ChartHeightWithPadding int
}

// CalculateChartDimensions computes the chart dimensions based on window size
func CalculateChartDimensions(windowWidth, windowHeight int) ChartDimensions {
	availableHeight := windowHeight - StatusBarHeight
	chartHeightWithPadding := availableHeight / GridRows
	chartWidthWithPadding := windowWidth / GridCols

	borderChars := 2
	titleLines := 1

	chartWidth := chartWidthWithPadding - borderChars
	chartHeight := chartHeightWithPadding - borderChars - titleLines

	// Ensure minimum size
	if chartHeight < MinChartHeight {
		chartHeight = MinChartHeight
	}
	if chartWidth < MinChartWidth {
		chartWidth = MinChartWidth
	}

	return ChartDimensions{
		ChartWidth:             chartWidth,
		ChartHeight:            chartHeight,
		ChartWidthWithPadding:  chartWidthWithPadding,
		ChartHeightWithPadding: chartHeightWithPadding,
	}
}
