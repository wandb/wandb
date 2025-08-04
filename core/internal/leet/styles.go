package leet

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

// System metrics grid configuration
const (
	MetricsGridRows      = 3
	MetricsGridCols      = 2
	MetricsPerPage       = MetricsGridRows * MetricsGridCols
	MinMetricChartWidth  = 18
	MinMetricChartHeight = 4
)

// Sidebar constants
const (
	SidebarWidthRatio     = 0.382
	SidebarWidthRatioBoth = 0.236 // When both sidebars visible: 0.382 * 0.618 ≈ 0.236
	SidebarMinWidth       = 40
	SidebarMaxWidth       = 80
)

// WANDB brand color
const wandbColor = lipgloss.Color("#FCBC32")

// const wandbColor = lipgloss.Color("#FFCF4F")

// ASCII art for the loading screen and the help page
var wandbArt = `
██     ██  █████  ███    ██ ██████  ██████
██     ██ ██   ██ ████   ██ ██   ██ ██   ██
██  █  ██ ███████ ██ ██  ██ ██   ██ ██████
██ ███ ██ ██   ██ ██  ██ ██ ██   ██ ██   ██
 ███ ███  ██   ██ ██   ████ ██████  ██████

`

const leetArt = `
██      ███████ ███████ ████████
██      ██      ██         ██
██      █████   █████      ██
██      ██      ██         ██
███████ ███████ ███████    ██
`

// Chart colors
// TODO: talk to design, adhere to our official color scheme.

// var graphColors = []string{"4", "10", "5", "6", "3", "2", "13", "14", "11", "9", "12", "1", "7", "8", "15"}

var graphColors = []string{
	"#E281FE",
	"#E78DE3",
	"#E993D5",
	"#ED9FBB",
	"#F0A5AD",
	"#F2AB9F",
	"#F6B784",
	"#F8BD78",
	"#FBC36B",
	"#FFCF4F",
}

// var graphColors = []string{
// 	"#E587EF",
// 	"#E589EC",
// 	"#E68BE6",
// 	"#E78DE3",
// 	"#E88FDE",
// 	"#E891D9",
// 	"#E993D5",
// 	"#EA95D1",
// 	"#EA97CC",
// 	"#EB99C8",
// 	"#EC9BC4",
// 	"#ED9DBF",
// 	"#ED9FBB",
// 	"#EEA1B6",
// 	"#EFA3B1",
// 	"#F0A5AD",
// 	"#F0A7A8",
// 	"#F1A9A4",
// 	"#F2AB9F",
// 	"#F3AD9B",
// 	"#F3AF98",
// 	"#F4B192",
// 	"#F5B38E",
// 	"#F6B688",
// 	"#F6B784",
// 	"#F7B980",
// 	"#F8BC7B",
// 	"#F8BD78",
// 	"#F9BF73",
// 	"#FAC26D",
// 	"#FBC36B",
// 	"#FCC565",
// 	"#FCC761",
// 	"#FDC95C",
// 	"#FECB58",
// 	"#FFCD54",
// }

// Chart styles
var (
	borderStyle = lipgloss.NewStyle().
			BorderStyle(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("238")) // dark gray

	titleStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("250")). // light gray
			Bold(true)

	focusedBorderStyle = borderStyle.BorderForeground(lipgloss.Color("4"))

	axisStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("240")) // gray

	labelStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("245")) // light gray
)

// Status bar styles
var (
	// pageInfoStyle = lipgloss.NewStyle().
	// 	// Foreground(lipgloss.AdaptiveColor{Light: "#000000", Dark: "#FFFFFF"}).
	// 	// Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#0C8599"}).
	// 	Foreground(lipgloss.AdaptiveColor{Light: "#000000", Dark: "#2B3038"}).
	// 	Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#A9FDF2"}).
	// 	Padding(0, 1)

	statusBarStyle = lipgloss.NewStyle().
		// Foreground(lipgloss.AdaptiveColor{Light: "#FFFFFF", Dark: "#FFFFFF"}).
		// Background(lipgloss.AdaptiveColor{Light: "#45B7D1", Dark: "#1864AB"})
		Foreground(lipgloss.AdaptiveColor{Light: "#000000", Dark: "#2B3038"}).
		Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#E1F7FA"})
	// Background(lipgloss.AdaptiveColor{Light: "#4ECDC4", Dark: "#A9FDF2"})
)

// Sidebar styles
var (
	sidebarStyle        = lipgloss.NewStyle().Padding(0, 1)
	sidebarBorderStyle  = lipgloss.NewStyle().Border(lipgloss.Border{Right: "│"}).BorderForeground(lipgloss.Color("238"))
	sidebarHeaderStyle  = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("230")).MarginLeft(1)
	sidebarSectionStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("245")).Bold(true)
	sidebarKeyStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("241"))
	sidebarValueStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("252"))

	RightBorder = lipgloss.Border{
		Top:         " ",
		Bottom:      " ",
		Left:        "",
		Right:       "│",
		TopLeft:     " ",
		TopRight:    "│",
		BottomLeft:  " ",
		BottomRight: "│",
	}
)

// Right sidebar styles
var (
	rightSidebarStyle       = lipgloss.NewStyle().Padding(0, 1)
	rightSidebarBorderStyle = lipgloss.NewStyle().Border(lipgloss.Border{Left: "│"}).BorderForeground(lipgloss.Color("238"))
	rightSidebarHeaderStyle = lipgloss.NewStyle().Bold(true).Foreground(lipgloss.Color("230")).MarginLeft(1)

	LeftBorder = lipgloss.Border{
		Top:         " ",
		Bottom:      " ",
		Left:        "│",
		Right:       "",
		TopLeft:     "|",
		TopRight:    " ",
		BottomLeft:  "|",
		BottomRight: " ",
	}
)

// Help screen styles
var (
	helpKeyStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("230")).
			Width(20) // helpKeyWidth

	helpDescStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("245"))

	helpSectionStyle = lipgloss.NewStyle().
				Bold(true).
				Foreground(wandbColor).
				MarginTop(1).
				MarginBottom(1)

	helpContentStyle = lipgloss.NewStyle().
				MarginLeft(2).
				MarginTop(2)
)
