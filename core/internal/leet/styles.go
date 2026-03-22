package leet

import (
	"fmt"
	"image/color"
	"math"
	"os"
	"sync"
	"time"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
	"github.com/muesli/termenv"
)

// Terminal background detection (cached).
var (
	termBgOnce     sync.Once
	termBgR        uint8
	termBgG        uint8
	termBgB        uint8
	termBgDetected bool
)

// initTerminalBg queries the terminal for its background color (once).
func initTerminalBg() {
	termBgOnce.Do(func() {
		output := termenv.NewOutput(os.Stdout)
		bg := output.BackgroundColor()
		if bg == nil {
			return
		}

		// termenv.RGBColor is a string type like "#RRGGBB"
		if rgb, ok := bg.(termenv.RGBColor); ok {
			var r, g, b uint8
			if _, err := fmt.Sscanf(string(rgb), "#%02x%02x%02x", &r, &g, &b); err != nil {
				return
			}
			termBgR, termBgG, termBgB = r, g, b
			termBgDetected = true
		}
	})
}

// blendRGB blends (r,g,b) toward (tr,tg,tb) by alpha (0.0–1.0).
func blendRGB(r, g, b, tr, tg, tb uint8, alpha float64) color.Color {
	blend := func(base, target uint8) uint8 {
		return uint8(float64(base)*(1-alpha) + float64(target)*alpha)
	}
	return lipgloss.Color(fmt.Sprintf("#%02x%02x%02x",
		blend(r, tr), blend(g, tg), blend(b, tb),
	))
}

// getOddRunStyleColor returns a color 5% darker than the terminal background.
func getOddRunStyleColor() color.Color {
	initTerminalBg()

	if termBgDetected {
		return blendRGB(termBgR, termBgG, termBgB, 128, 128, 128, 0.05)
	}

	return compat.AdaptiveColor{
		Light: lipgloss.Color("#d0d0d0"),
		Dark:  lipgloss.Color("#1c1c1c"),
	}
}

// Immutable UI constants.
const (
	StatusBarHeight = 1
	// Horizontal padding for the status bar (left and right).
	StatusBarPadding = 1

	MinChartWidth        = 20
	MinChartHeight       = 5
	MinMetricChartWidth  = 18
	MinMetricChartHeight = 4
	ChartBorderSize      = 2
	ChartTitleHeight     = 1
	ChartHeaderHeight    = 1
)

// Default grid sizes
const (
	// Single-run mode.
	DefaultMetricsGridRows = 4
	DefaultMetricsGridCols = 3
	DefaultSystemGridRows  = 6
	DefaultSystemGridCols  = 2

	// Workspace mode.
	DefaultWorkspaceMetricsGridRows = 3
	DefaultWorkspaceMetricsGridCols = 3
	DefaultWorkspaceSystemGridRows  = 3
	DefaultWorkspaceSystemGridCols  = 3
)

// Sidebar constants.
const (
	// We are using the golden ratio `phi` for visually pleasing layout proportions.
	SidebarWidthRatio     = 0.382 // 1 - 1/phi
	SidebarWidthRatioBoth = 0.236 // When both sidebars visible: (1 - 1/phi) / phi ≈ 0.236
	SidebarMinWidth       = 40
	SidebarMaxWidth       = 120

	// Sidebar internal content padding (accounts for borders).
	leftSidebarContentPadding = 4

	// Key/value column width ratio.
	sidebarKeyWidthRatio = 0.4 // 40% of available width for keys

	// Sidebar content padding (accounts for borders and internal spacing).
	rightSidebarContentPadding = 3

	// sidebarVerticalBorderCols is the width (in terminal columns)
	// consumed by a sidebar's vertical border.
	// Both LeftBorder and RightBorder draw a single vertical rule.
	sidebarVerticalBorderCols = 1

	// Default grid height for system metrics when not calculated from terminal height.
	defaultSystemMetricsGridHeight = 40

	// Mouse click coordinate adjustments for border/padding.
	rightSidebarMouseClickPaddingOffset = 1
)

// Rune constants for UI drawing.
const (
	// verticalLine is ASCII vertical bar U+007C.
	// verticalLine rune = '\u007C' // |

	// BoxLightVertical is U+2502 and is "taller" than verticalLine.
	boxLightVertical rune = '\u2502' // │

	// unicodeEmDash is the em dash.
	unicodeEmDash rune = '\u2014'

	// unicodeSpace is the regular whitespace.
	unicodeSpace rune = '\u0020'

	// mediumShadeBlock is a medium-shaded block.
	mediumShadeBlock rune = '\u2592' // ▒
)

// WANDB brand colors.
var (
	// Primary colors.
	moon900    = lipgloss.Color("#171A1F")
	wandbColor = lipgloss.Color("#FCBC32")
)

// Secondary colors.
var teal450 = compat.AdaptiveColor{
	Light: lipgloss.Color("#10BFCC"),
	Dark:  lipgloss.Color("#E1F7FA"),
}

// Functional colors not specific to any visual component.
var (
	// Color for main items such as chart titles.
	colorAccent = compat.AdaptiveColor{
		Light: lipgloss.Color("#6c6c6c"),
		Dark:  lipgloss.Color("#bcbcbc"),
	}

	// Main text color that appears the most frequently on the screen.
	colorText = compat.AdaptiveColor{
		Light: lipgloss.Color("#8a8a8a"), // ANSI color 245
		Dark:  lipgloss.Color("#8a8a8a"),
	}

	// Color for extra or parenthetical text or information.
	// Axis lines in charts.
	colorSubtle = compat.AdaptiveColor{
		Light: lipgloss.Color("#585858"), // ANSI color 240
		Dark:  lipgloss.Color("#585858"),
	}

	// Color for layout elements, like borders and separator lines.
	colorLayout = compat.AdaptiveColor{
		Light: lipgloss.Color("#949494"),
		Dark:  lipgloss.Color("#444444"),
	}

	colorDark = lipgloss.Color("#171717")

	// Color for layout elements when they're highlighted or focused.
	colorLayoutHighlight = teal450

	// Color for top-level headings; least frequent.
	// Leet logo, help page section headings.
	colorHeading = wandbColor

	// Color for lower-level headings; more frequent than headings.
	// Help page keys, metrics grid header.
	colorSubheading = compat.AdaptiveColor{
		Light: lipgloss.Color("#3a3a3a"),
		Dark:  lipgloss.Color("#eeeeee"),
	}

	// Colors for key-value pairs such as run summary or config items.
	colorItemKey   = lipgloss.Color("243")
	colorItemValue = compat.AdaptiveColor{
		Light: lipgloss.Color("#262626"),
		Dark:  lipgloss.Color("#d0d0d0"),
	}

	// Color used for the selected line in lists.
	colorSelected = compat.AdaptiveColor{
		Dark:  lipgloss.Color("#FCBC32"),
		Light: lipgloss.Color("#FCBC32"),
	}
)

// ASCII art for the loading screen and the help page.
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

// A spherical cow in an AI bubble in a vacuum.
//
// nolint:staticcheck // colorized ASCII art.
const sphericalCowInAVacuum = `
[38;2;13;0;0m [38;2;7;0;0m    [38;2;6;0;0m  [38;2;7;0;0m [38;2;255;38;0m⠈[38;2;255;39;0m⠁[38;2;8;0;0m [38;2;7;0;0m  [38;2;8;0;0m [38;2;7;0;0m [38;2;6;0;0m [38;2;7;0;0m   [38;2;6;0;0m [38;2;14;0;0m [38;2;15;1;0m [38;2;7;0;0m [38;2;255;52;0m⢠[38;2;255;56;5m⡤[38;2;14;0;0m [38;2;255;53;0m⢤[38;2;255;55;5m⡤[38;2;13;0;0m [38;2;255;70;4m⣤[38;2;255;66;0m⡤[38;2;255;53;0m⠠[38;2;255;74;4m⣤[38;2;255;72;4m⣤[38;2;9;0;0m [38;2;255;57;0m⢤[38;2;14;0;0m [38;2;23;3;0m [38;2;17;1;0m [38;2;7;0;0m         [38;2;6;0;0m [38;2;7;0;0m [38;2;8;0;0m [38;2;255;55;0m⠰[38;2;255;45;0m⠆[38;2;8;0;0m  [38;2;7;0;0m   [38;2;6;0;0m [38;2;7;0;0m
[38;2;8;0;0m [38;2;7;0;0m  [38;2;8;0;0m [38;2;11;0;0m [38;2;8;0;0m [38;2;7;0;0m [38;2;6;0;0m  [38;2;7;0;0m   [38;2;8;0;0m  [38;2;11;0;0m  [38;2;255;41;0m⢀[38;2;255;47;0m⡄[38;2;255;49;0m⠰[38;2;255;37;0m⠂[38;2;255;38;0m⠈[38;2;255;53;0m⠉[38;2;9;0;0m   [38;2;8;0;0m  [38;2;9;0;0m   [38;2;8;0;0m [38;2;9;0;0m [38;2;10;0;0m [38;2;9;0;0m [38;2;8;0;0m [38;2;9;0;0m [38;2;12;1;0m [38;2;255;63;0m⠉[38;2;255;51;0m⠁[38;2;8;0;0m [38;2;255;51;0m⠰[38;2;24;3;0m [38;2;255;54;0m⣀[38;2;13;1;0m [38;2;10;0;0m [38;2;8;0;0m   [38;2;7;0;0m   [38;2;8;0;0m [38;2;7;0;0m [38;2;8;0;0m     [38;2;7;0;0m [38;2;8;0;0m
[38;2;7;0;0m    [38;2;255;49;0m⠘[38;2;22;2;0m [38;2;7;0;0m [38;2;6;0;0m  [38;2;7;0;0m  [38;2;247;59;0m⢀[38;2;251;69;0m⣠[38;2;255;46;0m⠄[38;2;255;57;5m⠛[38;2;255;55;0m⠁[38;2;8;0;0m [38;2;11;0;0m [38;2;8;0;0m  [38;2;9;0;0m [38;2;8;0;0m    [38;2;9;0;0m [38;2;8;0;0m [38;2;9;0;0m [38;2;21;3;0m [38;2;9;0;0m [38;2;8;0;0m    [38;2;7;0;0m [38;2;9;0;0m [38;2;8;0;0m [38;2;9;0;0m  [38;2;8;0;0m [38;2;9;0;0m [38;2;8;0;0m [38;2;18;1;0m [38;2;255;45;0m⠘[38;2;255;61;0m⠃[38;2;9;0;0m [38;2;8;0;0m [38;2;20;2;0m [38;2;7;0;0m     [38;2;8;0;0m    [38;2;7;0;0m [38;2;14;1;0m
[38;2;7;0;0m [38;2;6;0;0m [38;2;7;0;0m [38;2;6;0;0m  [38;2;7;0;0m   [38;2;8;0;0m [38;2;252;57;0m⢀[38;2;250;77;4m⡴[38;2;255;69;0m⠎[38;2;252;57;0m⠁[38;2;8;0;0m [38;2;9;0;0m  [38;2;249;60;0m⢀[38;2;248;64;0m⡀[38;2;8;0;0m [38;2;9;0;0m [38;2;10;0;0m [38;2;9;0;0m     [38;2;8;0;0m [38;2;11;0;0m [38;2;255;61;6m⠉[38;2;11;0;0m [38;2;9;0;0m  [38;2;10;0;0m [38;2;8;0;0m [38;2;9;0;0m  [38;2;242;75;4m⣤[38;2;239;74;5m⣄[38;2;10;0;0m [38;2;9;0;0m  [38;2;10;0;0m [38;2;9;0;0m     [38;2;255;50;0m⠉[38;2;16;2;0m [38;2;255;63;0m⣀[38;2;8;0;0m        [38;2;255;54;0m⠈[38;2;255;53;0m⠁
[38;2;7;0;0m      [38;2;8;0;0m [38;2;255;60;0m⣀[38;2;252;77;4m⡴[38;2;245;75;4m⠛[38;2;255;48;0m⠁[38;2;8;0;0m [38;2;7;0;0m [38;2;9;0;0m  [38;2;223;96;3m⢸[38;2;255;127;7m⣿[38;2;255;117;5m⣷[38;2;213;77;0m⡄[38;2;9;0;0m       [38;2;8;0;0m [38;2;9;0;0m [38;2;8;0;0m [38;2;9;0;0m     [38;2;8;0;0m [38;2;216;92;3m⣤[38;2;255;126;5m⣿[38;2;255;126;7m⣿[38;2;232;98;5m⡇[38;2;9;0;0m      [38;2;8;0;0m [38;2;9;0;0m [38;2;8;0;0m [38;2;10;0;0m [38;2;255;56;0m⠘[38;2;255;74;4m⠳[38;2;255;62;0m⣄[38;2;255;37;0m⡀[38;2;8;0;0m    [38;2;7;0;0m [38;2;6;0;0m [38;2;7;0;0m
  [38;2;6;0;0m [38;2;8;0;0m  [38;2;255;62;0m⢠[38;2;255;73;4m⡶[38;2;255;65;0m⠋[38;2;9;0;0m [38;2;7;0;0m [38;2;255;51;0m⠐[38;2;255;62;0m⠂[38;2;8;0;0m  [38;2;218;75;0m⢰[38;2;249;144;6m⣿[38;2;255;152;7m⣿[38;2;255;143;6m⣿[38;2;245;103;4m⣧[38;2;18;4;0m [38;2;10;0;0m [38;2;12;0;0m [38;2;255;55;0m⢀[38;2;229;86;3m⣤[38;2;226;88;3m⣤[38;2;234;86;3m⣤[38;2;234;87;3m⣤[38;2;242;82;3m⣤[38;2;252;77;4m⣤[38;2;243;80;4m⣤[38;2;242;81;4m⣤[38;2;227;76;0m⡄[38;2;9;0;0m [38;2;10;0;0m [38;2;208;83;0m⢠[38;2;246;130;5m⣿[38;2;255;142;6m⣿[38;2;255;139;6m⣿[38;2;234;106;4m⡇[38;2;9;0;0m [38;2;8;0;0m [38;2;9;0;0m [38;2;8;0;0m  [38;2;255;61;0m⠘[38;2;255;60;0m⠃[38;2;8;0;0m [38;2;7;0;0m    [38;2;255;41;0m⠈[38;2;255;64;5m⠱[38;2;255;52;0m⠂[38;2;8;0;0m   [38;2;7;0;0m
    [38;2;255;65;5m⢠[38;2;255;58;0m⡄[38;2;10;0;0m [38;2;9;0;0m [38;2;233;68;0m⣀[38;2;241;64;0m⣀[38;2;237;67;0m⣀[38;2;233;68;0m⣀[38;2;255;48;0m⡀[38;2;8;0;0m [38;2;255;49;0m⠈[38;2;218;116;4m⢻[38;2;243;137;6m⣿[38;2;217;103;5m⠛[38;2;223;72;0m⠃[38;2;11;0;0m [38;2;226;88;3m⣘[38;2;230;114;4m⣻[38;2;255;187;6m⣿[38;2;255;202;7m⣿[38;2;255;196;7m⣿[38;2;255;205;7m⣿[38;2;255;212;8m⣿[38;2;255;201;7m⣿[38;2;207;120;4m⠛[38;2;21;3;0m [38;2;20;3;0m [38;2;14;2;0m [38;2;249;60;0m⠠[38;2;236;103;5m⣾[38;2;255;138;6m⣿[38;2;255;152;7m⣿[38;2;255;147;6m⣿[38;2;244;124;5m⡿[38;2;214;84;4m⠃[38;2;9;0;0m     [38;2;8;0;0m    [38;2;7;0;0m  [38;2;8;0;0m  [38;2;7;0;0m [38;2;253;68;5m⠘[38;2;253;61;0m⢀[38;2;10;0;0m [38;2;8;0;0m
[38;2;7;0;0m  [38;2;8;0;0m [38;2;255;61;0m⠰[38;2;255;59;0m⠆[38;2;9;0;0m [38;2;12;1;0m [38;2;255;95;5m⣶[38;2;255;94;5m⠿[38;2;241;72;0m⠉[38;2;235;75;0m⠉[38;2;237;74;5m⠉[38;2;246;76;4m⠱[38;2;248;73;4m⣆[38;2;255;53;0m⡀[38;2;200;77;0m⢀[38;2;179;108;3m⣄[38;2;180;99;4m⢠[38;2;212;158;6m⣶[38;2;228;180;5m⣶[38;2;255;210;7m⣿[38;2;255;219;8m⣿[38;2;255;222;8m⣿[38;2;255;225;8m⣿[38;2;255;224;8m⣿[38;2;255;221;8m⣿[38;2;255;218;8m⣿[38;2;255;214;8m⣿[38;2;223;169;6m⣶[38;2;182;119;2m⣤[38;2;173;103;3m⣄[38;2;10;0;0m [38;2;9;0;0m  [38;2;215;74;0m⠈[38;2;212;87;4m⠉[38;2;207;87;4m⠉[38;2;11;0;0m [38;2;9;0;0m  [38;2;255;60;0m⢀[38;2;238;84;3m⡶[38;2;235;88;3m⠶⠶[38;2;232;91;3m⠶[38;2;230;91;3m⠶[38;2;220;86;4m⢆[38;2;248;64;0m⡀[38;2;7;0;0m   [38;2;8;0;0m  [38;2;7;0;0m [38;2;251;63;0m⠉[38;2;244;69;5m⣀[38;2;13;1;0m [38;2;7;0;0m [38;2;8;0;0m [38;2;7;0;0m
[38;2;8;0;0m  [38;2;255;51;0m⠐[38;2;255;57;0m⠂[38;2;8;0;0m  [38;2;12;0;0m [38;2;244;85;3m⠛[38;2;255;69;4m⣤[38;2;255;46;0m⣀[38;2;255;37;0m⡀[38;2;9;0;0m  [38;2;205;82;0m⣈[38;2;212;144;5m⣴[38;2;255;204;7m⣿[38;2;255;215;8m⣿[38;2;255;215;7m⣿[38;2;255;221;8m⣿[38;2;255;220;8m⣿⣿⣿[38;2;255;221;8m⣿[38;2;255;223;8m⣿⣿[38;2;255;222;8m⣿⣿[38;2;255;220;8m⣿[38;2;255;221;8m⣿[38;2;255;218;8m⣿[38;2;255;209;7m⣿[38;2;255;190;6m⣿[38;2;223;163;4m⣧[38;2;205;135;4m⣤[38;2;207;133;4m⣤[38;2;209;130;4m⣤[38;2;207;133;4m⣤[38;2;207;122;4m⣴[38;2;228;79;0m⠓[38;2;253;66;0m⠘[38;2;249;70;0m⠋[38;2;15;2;0m [38;2;10;0;0m  [38;2;9;0;0m [38;2;15;2;0m [38;2;220;97;3m⣸[38;2;234;102;5m⡇[38;2;8;0;0m [38;2;7;0;0m  [38;2;8;0;0m [38;2;7;0;0m [38;2;8;0;0m  [38;2;255;53;0m⠈[38;2;255;64;5m⣤[38;2;10;0;0m [38;2;7;0;0m [38;2;8;0;0m
[38;2;7;0;0m [38;2;255;46;0m⠐[38;2;255;57;0m⠆[38;2;8;0;0m [38;2;7;0;0m   [38;2;8;0;0m [38;2;16;2;0m [38;2;255;66;5m⠉[38;2;255;49;0m⠁[38;2;10;0;0m [38;2;204;132;4m⣶[38;2;255;204;7m⣿[38;2;255;221;8m⣿[38;2;255;222;8m⣿[38;2;255;224;8m⣿[38;2;255;222;8m⣿[38;2;255;223;8m⣿[38;2;255;219;8m⣿[38;2;255;221;8m⣿[38;2;255;220;8m⣿[38;2;255;219;8m⣿[38;2;255;223;8m⣿[38;2;255;224;8m⣿[38;2;255;221;8m⣿⣿[38;2;255;220;8m⣿[38;2;255;221;8m⣿[38;2;255;220;8m⣿[38;2;255;219;8m⣿[38;2;255;220;8m⣿[38;2;255;222;7m⣿[38;2;255;222;8m⣿[38;2;255;221;8m⣿[38;2;255;222;8m⣿[38;2;255;221;8m⣿[38;2;251;196;6m⣿[38;2;187;116;2m⣤[38;2;188;89;0m⡀[38;2;12;0;0m [38;2;209;86;4m⣠[38;2;199;98;3m⣤[38;2;210;104;5m⣰[38;2;234;135;5m⣶[38;2;235;125;5m⣾[38;2;227;108;4m⠟[38;2;215;74;0m⠁[38;2;14;2;0m [38;2;255;50;0m⡀[38;2;8;0;0m  [38;2;19;3;0m [38;2;238;73;5m⠆[38;2;8;0;0m  [38;2;16;1;0m [38;2;255;60;0m⣀[38;2;8;0;0m [38;2;7;0;0m
[38;2;14;1;0m [38;2;255;65;4m⡤[38;2;9;0;0m   [38;2;8;0;0m   [38;2;9;0;0m  [38;2;173;104;3m⢠[38;2;239;169;5m⣾[38;2;255;208;7m⣿[38;2;253;196;7m⣿[38;2;205;143;5m⠟[38;2;199;140;5m⠛[38;2;199;141;5m⠛[38;2;222;164;6m⢻[38;2;255;206;7m⣿[38;2;255;216;8m⣿[38;2;255;220;8m⣿[38;2;255;219;8m⣿⣿[38;2;255;221;8m⣿[38;2;255;222;8m⣿[38;2;255;218;8m⣿[38;2;255;217;8m⣿[38;2;255;213;7m⣿[38;2;248;189;6m⣿[38;2;202;145;5m⠛[38;2;204;144;3m⠛[38;2;206;145;5m⠛[38;2;232;176;5m⢿[38;2;255;211;7m⣿[38;2;255;220;8m⣿⣿[38;2;255;219;8m⣿⣿[38;2;255;220;8m⣿[38;2;255;208;7m⣿[38;2;255;199;7m⣿⣿⣿[38;2;255;201;7m⣿[38;2;255;210;7m⣿[38;2;222;160;4m⣿[38;2;6;0;0m [38;2;7;0;0m [38;2;10;1;0m [38;2;255;63;0m⠑[38;2;241;64;0m⠂[38;2;8;0;0m  [38;2;7;0;0m  [38;2;8;0;0m [38;2;12;0;0m [38;2;255;51;0m⠁[38;2;8;0;0m [38;2;7;0;0m
[38;2;16;1;0m [38;2;255;60;5m⠶[38;2;9;0;0m [38;2;10;0;0m [38;2;8;0;0m [38;2;255;54;5m⣠[38;2;23;3;0m [38;2;10;0;0m  [38;2;187;84;0m⢠[38;2;224;158;6m⣼[38;2;255;216;8m⣿[38;2;214;145;5m⡏[38;2;217;69;0m⠁[38;2;13;0;0m [38;2;206;77;0m⠰[38;2;194;120;4m⠶[38;2;10;0;0m [38;2;218;162;6m⣿[38;2;255;217;8m⣿[38;2;255;219;8m⣿⣿⣿[38;2;255;221;8m⣿[38;2;255;220;8m⣿[38;2;255;218;8m⣿[38;2;255;214;7m⣿[38;2;194;117;5m⡏[38;2;212;71;0m⠠[38;2;203;126;4m⡶[38;2;12;0;0m [38;2;11;0;0m  [38;2;179;101;3m⠉[38;2;250;195;6m⣿[38;2;255;219;8m⣿⣿[38;2;255;220;8m⣿⣿[38;2;255;219;8m⣿[38;2;255;214;8m⣿[38;2;244;183;6m⡿[38;2;225;167;6m⠿[38;2;223;164;6m⠿[38;2;238;174;5m⢿[38;2;241;168;5m⣿[38;2;176;100;0m⡄[38;2;7;0;0m [38;2;6;0;0m [38;2;7;0;0m [38;2;9;0;0m [38;2;244;90;3m⣶[38;2;16;2;0m [38;2;10;0;0m [38;2;9;0;0m [38;2;8;0;0m [38;2;9;0;0m [38;2;247;59;0m⠐[38;2;252;71;4m⠖[38;2;9;0;0m
[38;2;17;1;0m [38;2;255;60;0m⠆[38;2;9;0;0m   [38;2;15;1;0m [38;2;10;0;0m  [38;2;15;2;0m [38;2;204;126;4m⣸[38;2;255;216;8m⣿⣿[38;2;215;154;5m⣧[38;2;195;78;0m⡀[38;2;12;0;0m [38;2;11;0;0m  [38;2;183;89;0m⢀[38;2;235;169;5m⣿[38;2;255;214;7m⣿[38;2;255;216;7m⣿[38;2;255;215;7m⣿[38;2;255;214;7m⣿[38;2;255;216;7m⣿[38;2;255;217;7m⣿[38;2;255;213;8m⣿[38;2;255;211;7m⣿[38;2;186;111;3m⣇[38;2;11;1;0m [38;2;10;0;0m    [38;2;178;100;4m⣀[38;2;247;191;6m⣿[38;2;255;216;8m⣿⣿[38;2;255;215;8m⣿[38;2;255;218;8m⣿[38;2;255;202;7m⣿[38;2;200;130;4m⡏[38;2;14;2;0m [38;2;10;0;0m  [38;2;13;1;0m [38;2;179;100;3m⠙[38;2;230;159;4m⢻[38;2;193;126;4m⡇[38;2;9;0;0m [38;2;8;0;0m [38;2;9;0;0m [38;2;13;1;0m [38;2;228;89;3m⣤[38;2;14;1;0m [38;2;9;0;0m  [38;2;10;0;0m [38;2;14;1;0m [38;2;238;75;4m⠦[38;2;10;0;0m
[38;2;17;1;0m [38;2;255;61;0m⠖[38;2;9;0;0m      [38;2;225;70;0m⠈[38;2;255;169;7m⣿[38;2;255;218;8m⣿[38;2;255;219;8m⣿[38;2;255;218;8m⣿[38;2;255;196;6m⣿[38;2;244;175;7m⣿[38;2;210;131;4m⣿[38;2;213;121;4m⣷[38;2;221;118;4m⣬[38;2;228;125;6m⣭[38;2;228;122;4m⣭[38;2;228;127;5m⣭[38;2;229;126;4m⣭[38;2;228;130;5m⣭[38;2;233;127;5m⣭[38;2;230;130;4m⣭[38;2;228;127;5m⣭[38;2;224;148;5m⡿[38;2;231;154;4m⢿[38;2;242;173;5m⣿[38;2;200;134;4m⣤[38;2;201;133;4m⣤[38;2;198;134;4m⣤[38;2;229;167;6m⣾[38;2;255;207;7m⣿[38;2;255;219;8m⣿[38;2;255;218;8m⣿[38;2;255;220;8m⣿[38;2;255;214;8m⣿[38;2;230;172;5m⣿[38;2;187;88;0m⠁[38;2;9;0;0m      [38;2;200;134;4m⢸[38;2;255;194;6m⣿[38;2;216;146;5m⣦[38;2;194;82;0m⡄[38;2;15;2;0m  [38;2;228;95;3m⠿[38;2;16;2;0m [38;2;9;0;0m [38;2;10;0;0m [38;2;9;0;0m [38;2;16;2;0m [38;2;238;76;4m⠖[38;2;10;0;0m
[38;2;18;2;0m [38;2;254;68;0m⠖[38;2;8;0;0m [38;2;9;0;0m [38;2;10;0;0m [38;2;14;1;0m [38;2;9;0;0m [38;2;10;0;0m [38;2;221;71;0m⢠[38;2;255;167;7m⣿[38;2;255;219;8m⣿⣿[38;2;255;216;7m⣿[38;2;212;138;5m⡟[38;2;228;131;5m⣿[38;2;254;156;7m⣿[38;2;246;148;6m⣿[38;2;231;127;5m⠿[38;2;251;144;6m⣿[38;2;255;154;7m⣿[38;2;255;156;7m⣿[38;2;255;157;7m⣿[38;2;254;151;6m⣿[38;2;238;138;6m⠿[38;2;245;151;6m⣿[38;2;255;159;7m⣿[38;2;254;156;7m⣿[38;2;252;153;6m⣿[38;2;225;125;6m⣾[38;2;213;144;5m⢻[38;2;255;217;7m⣿[38;2;255;220;8m⣿[38;2;255;219;8m⣿⣿⣿[38;2;255;216;8m⣿[38;2;255;199;7m⣿[38;2;194;116;5m⠛[38;2;255;48;0m⠁[38;2;9;0;0m   [38;2;10;0;0m [38;2;9;0;0m [38;2;10;0;0m [38;2;8;0;0m [38;2;183;97;0m⠘[38;2;202;132;4m⠛[38;2;238;168;5m⢿[38;2;255;206;7m⣿[38;2;255;212;7m⣿[38;2;255;188;7m⣿[38;2;201;95;3m⣆[38;2;11;0;0m [38;2;9;0;0m [38;2;8;0;0m [38;2;9;0;0m [38;2;17;3;0m [38;2;222;81;4m⠓[38;2;9;0;0m
[38;2;255;51;0m⠠[38;2;251;69;0m⡄[38;2;8;0;0m [38;2;9;0;0m [38;2;17;3;0m [38;2;235;77;4m⠛[38;2;9;0;0m  [38;2;224;70;0m⠈[38;2;255;159;7m⣿[38;2;255;218;8m⣿⣿[38;2;255;213;7m⣿[38;2;190;97;3m⡇[38;2;242;154;6m⣿[38;2;254;161;7m⣿[38;2;252;153;6m⣿[38;2;228;126;5m⣧[38;2;240;136;5m⣿[38;2;255;153;7m⣿[38;2;255;156;7m⣿[38;2;255;157;7m⣿[38;2;247;152;6m⣿[38;2;207;110;5m⣤[38;2;232;135;5m⣼[38;2;254;162;7m⣿[38;2;253;162;7m⣿[38;2;255;160;7m⣿[38;2;239;144;6m⣿[38;2;176;103;3m⢸[38;2;255;216;7m⣿[38;2;255;221;8m⣿[38;2;255;220;8m⣿[38;2;255;217;8m⣿[38;2;255;218;8m⣿[38;2;255;217;8m⣿[38;2;254;192;6m⣿[38;2;255;44;0m⡀[38;2;10;0;0m [38;2;9;0;0m [38;2;8;0;0m  [38;2;9;0;0m   [38;2;8;0;0m [38;2;9;0;0m [38;2;10;0;0m [38;2;14;0;0m [38;2;254;194;6m⣿[38;2;255;211;7m⣿[38;2;255;172;7m⣿[38;2;245;155;6m⣿[38;2;15;1;0m [38;2;8;0;0m   [38;2;17;3;0m [38;2;232;80;4m⣤[38;2;9;0;0m
[38;2;8;0;0m [38;2;255;42;0m⢀[38;2;255;60;0m⡀[38;2;8;0;0m [38;2;9;0;0m [38;2;8;0;0m [38;2;10;0;0m [38;2;9;0;0m [38;2;10;0;0m [38;2;190;109;3m⢸[38;2;255;214;7m⣿[38;2;255;217;8m⣿[38;2;255;216;8m⣿[38;2;202;123;4m⣇[38;2;234;134;5m⣿[38;2;253;157;7m⣿[38;2;255;159;7m⣿[38;2;255;158;7m⣿[38;2;255;155;7m⣿[38;2;254;158;7m⣿[38;2;254;160;7m⣿[38;2;255;160;7m⣿[38;2;254;161;7m⣿[38;2;254;163;7m⣿[38;2;254;160;7m⣿[38;2;255;157;7m⣿[38;2;255;156;7m⣿[38;2;255;154;6m⣿[38;2;234;128;5m⣿[38;2;195;127;4m⣸[38;2;255;216;8m⣿[38;2;255;221;8m⣿⣿[38;2;255;219;8m⣿[38;2;255;218;8m⣿[38;2;255;219;8m⣿[38;2;255;216;8m⣿[38;2;255;196;7m⣿[38;2;201;141;5m⣦[38;2;175;108;3m⣀[38;2;190;80;0m⡀[38;2;10;0;0m  [38;2;9;0;0m    [38;2;10;0;0m [38;2;189;98;3m⣀[38;2;255;195;6m⣿[38;2;255;183;8m⣿[38;2;252;161;7m⣿[38;2;206;108;5m⠛[38;2;12;0;0m [38;2;9;0;0m  [38;2;12;1;0m [38;2;236;71;0m⣀[38;2;9;0;0m [38;2;8;0;0m
 [38;2;11;0;0m [38;2;255;50;0m⢀[38;2;255;34;0m⡀[38;2;8;0;0m [38;2;9;0;0m   [38;2;10;0;0m [38;2;222;67;0m⠈[38;2;202;131;4m⢹[38;2;255;205;7m⣿[38;2;255;218;8m⣿[38;2;255;215;7m⣿[38;2;251;185;6m⣿[38;2;224;148;5m⣭[38;2;222;139;5m⣽[38;2;226;123;6m⡿[38;2;228;124;6m⠿⠿⢿[38;2;231;123;6m⡿[38;2;225;125;6m⠿[38;2;225;126;5m⠿[38;2;226;126;5m⠿[38;2;235;120;6m⢿[38;2;225;140;5m⣯[38;2;229;154;6m⣽[38;2;254;194;6m⣿[38;2;255;216;7m⣿[38;2;255;219;7m⣿[38;2;255;217;7m⣿[38;2;255;211;7m⣿[38;2;255;206;7m⣿[38;2;255;207;7m⣿⣿[38;2;255;211;7m⣿[38;2;255;217;8m⣿[38;2;255;220;8m⣿[38;2;255;219;8m⣿[38;2;226;161;6m⡿[38;2;211;73;0m⠂[38;2;10;0;0m [38;2;9;0;0m   [38;2;255;47;0m⢀[38;2;218;150;5m⣾[38;2;255;200;7m⣿[38;2;255;185;7m⣿[38;2;252;174;8m⣿[38;2;219;127;6m⡿[38;2;20;4;0m [38;2;9;0;0m  [38;2;11;0;0m [38;2;255;60;0m⣀[38;2;245;63;0m⠉[38;2;8;0;0m
[38;2;9;0;0m [38;2;8;0;0m [38;2;255;54;0m⠈[38;2;251;69;5m⢁[38;2;255;48;0m⡀[38;2;8;0;0m    [38;2;9;0;0m [38;2;210;76;0m⠘[38;2;225;137;5m⢻[38;2;255;188;7m⣿[38;2;255;213;7m⣿[38;2;255;219;8m⣿[38;2;255;217;8m⣿[38;2;255;218;8m⣿[38;2;255;215;7m⣿⣿[38;2;255;212;7m⣿⣿⣿⣿[38;2;255;214;7m⣿⣿[38;2;255;213;7m⣿[38;2;255;220;8m⣿⣿[38;2;255;219;8m⣿[38;2;255;213;7m⣿[38;2;228;166;6m⡿[38;2;181;111;3m⠋[38;2;17;1;0m [38;2;16;1;0m  [38;2;17;1;0m [38;2;195;89;0m⠸[38;2;252;185;6m⢿[38;2;255;220;8m⣿[38;2;255;219;8m⣿[38;2;241;184;6m⣷[38;2;185;119;5m⣄[38;2;179;109;3m⣀[38;2;176;111;3m⣀[38;2;174;113;3m⣀[38;2;193;138;4m⣴[38;2;249;187;6m⣾[38;2;255;195;7m⣿[38;2;255;177;8m⣿[38;2;252;173;7m⣿[38;2;234;146;6m⡿[38;2;195;79;0m⠇[38;2;9;0;0m   [38;2;212;79;0m⣀[38;2;244;68;0m⠉[38;2;10;0;0m [38;2;8;0;0m [38;2;9;0;0m
[38;2;8;0;0m [38;2;7;0;0m [38;2;8;0;0m [38;2;253;58;0m⠈[38;2;255;70;4m⢡[38;2;19;3;0m [38;2;9;0;0m    [38;2;10;0;0m [38;2;239;62;0m⠈[38;2;229;126;5m⢿[38;2;254;170;7m⣿[38;2;255;205;8m⣿[38;2;255;217;8m⣿[38;2;255;220;8m⣿[38;2;255;215;7m⣿[38;2;255;209;7m⣿[38;2;255;217;7m⣿[38;2;255;220;8m⣿[38;2;255;219;8m⣿[38;2;255;220;8m⣿[38;2;255;223;8m⣿⣿[38;2;255;219;8m⣿[38;2;255;220;8m⣿[38;2;255;219;8m⣿[38;2;255;218;8m⣿[38;2;242;189;6m⣿[38;2;11;0;0m [38;2;10;0;0m [38;2;11;0;0m [38;2;10;0;0m   [38;2;11;0;0m [38;2;188;111;5m⢸[38;2;255;218;8m⣿[38;2;255;221;8m⣿[38;2;255;219;8m⣿[38;2;255;215;8m⣿[38;2;255;217;8m⣿[38;2;255;216;8m⣿[38;2;255;215;8m⣿[38;2;255;203;7m⣿[38;2;255;185;7m⣿[38;2;255;163;7m⣿[38;2;250;153;6m⣿[38;2;195;100;3m⡏[38;2;14;2;0m [38;2;9;0;0m   [38;2;242;75;4m⢤[38;2;233;72;0m⠍[38;2;9;0;0m  [38;2;8;0;0m
   [38;2;9;0;0m [38;2;10;0;0m [38;2;255;64;0m⠰[38;2;240;72;0m⣄[38;2;15;2;0m [38;2;18;3;0m [38;2;252;71;4m⠓[38;2;9;0;0m [38;2;10;0;0m  [38;2;205;92;4m⠙[38;2;229;128;5m⠿[38;2;255;172;7m⣿[38;2;245;177;5m⣿[38;2;184;100;3m⠋[38;2;15;0;0m [38;2;186;114;2m⠛[38;2;235;171;5m⢿[38;2;255;213;7m⣿[38;2;255;219;7m⣿[38;2;255;222;8m⣿⣿[38;2;255;219;8m⣿[38;2;255;220;8m⣿⣿[38;2;255;219;8m⣿[38;2;255;209;7m⣿[38;2;211;154;5m⣶[38;2;176;99;4m⣀[38;2;12;0;0m [38;2;11;0;0m  [38;2;17;2;0m [38;2;184;124;4m⣰[38;2;240;184;6m⣾[38;2;255;220;8m⣿⣿[38;2;255;218;8m⣿[38;2;255;214;8m⣿[38;2;255;200;7m⣿[38;2;255;178;6m⣿[38;2;255;173;6m⣿[38;2;255;158;7m⣿[38;2;247;139;6m⡿[38;2;216;108;5m⠟[38;2;227;66;0m⠁[38;2;10;0;0m [38;2;9;0;0m  [38;2;255;56;0m⢀[38;2;239;78;4m⡰[38;2;255;46;0m⠄[38;2;9;0;0m [38;2;8;0;0m [38;2;7;0;0m [38;2;8;0;0m
[38;2;255;69;4m⠶[38;2;11;0;0m [38;2;8;0;0m [38;2;7;0;0m   [38;2;232;66;0m⠈[38;2;243;80;4m⠳[38;2;255;69;4m⣤[38;2;14;0;0m [38;2;9;0;0m    [38;2;11;0;0m [38;2;215;74;0m⠉[38;2;219;82;4m⠙[38;2;227;90;3m⢣[38;2;227;74;0m⡄[38;2;10;0;0m [38;2;23;5;0m [38;2;253;164;7m⣿[38;2;255;203;7m⣿[38;2;255;212;7m⣿[38;2;255;215;7m⣿[38;2;255;212;7m⣿[38;2;255;213;7m⣿[38;2;255;211;7m⣿⣿[38;2;255;210;7m⣿[38;2;255;213;7m⣿[38;2;255;206;7m⣿[38;2;255;198;6m⣿[38;2;255;196;7m⣿[38;2;254;199;7m⣿[38;2;255;200;7m⣿[38;2;255;215;7m⣿[38;2;255;213;7m⣿[38;2;255;202;7m⣿[38;2;255;193;7m⣿[38;2;255;175;6m⣿[38;2;255;146;6m⣿[38;2;255;140;6m⣿[38;2;255;139;6m⣿[38;2;252;129;7m⣿[38;2;215;95;3m⠋[38;2;255;54;0m⠁[38;2;10;0;0m [38;2;8;0;0m [38;2;9;0;0m [38;2;255;48;0m⢀[38;2;237;69;0m⡀[38;2;252;57;0m⠈[38;2;241;60;0m⠁[38;2;8;0;0m [38;2;7;0;0m    [38;2;238;98;5m⣶
[38;2;7;0;0m  [38;2;8;0;0m  [38;2;7;0;0m  [38;2;8;0;0m [38;2;9;0;0m [38;2;18;3;0m [38;2;246;76;4m⠻[38;2;255;52;0m⠄[38;2;8;0;0m [38;2;9;0;0m  [38;2;10;0;0m [38;2;8;0;0m [38;2;9;0;0m [38;2;13;0;0m [38;2;239;99;5m⢹[38;2;254;103;4m⣷[38;2;244;95;5m⣟[38;2;239;104;5m⣛[38;2;250;118;6m⠿[38;2;251;123;5m⠿[38;2;248;126;5m⠿[38;2;255;136;6m⣿[38;2;255;142;6m⣿[38;2;255;139;6m⣿[38;2;255;142;7m⣿[38;2;255;141;6m⣿[38;2;255;138;6m⣿[38;2;242;123;5m⡟[38;2;235;160;6m⣿[38;2;255;212;7m⣿[38;2;255;217;8m⣿⣿[38;2;255;200;6m⣿[38;2;182;115;2m⠛[38;2;227;85;4m⠸[38;2;239;101;5m⠟[38;2;224;93;3m⠛[38;2;252;90;5m⣷[38;2;255;103;6m⣾[38;2;255;121;7m⣿[38;2;255;124;5m⣿[38;2;220;94;6m⠇[38;2;9;0;0m  [38;2;233;68;0m⣀[38;2;255;45;0m⡀[38;2;234;79;4m⠤[38;2;18;3;0m [38;2;8;0;0m [38;2;7;0;0m  [38;2;8;0;0m   [38;2;7;0;0m [38;2;224;80;4m⠙
[38;2;6;0;0m [38;2;7;0;0m    [38;2;6;0;0m [38;2;7;0;0m  [38;2;8;0;0m [38;2;7;0;0m [38;2;8;0;0m [38;2;248;69;0m⠰[38;2;255;46;0m⠂[38;2;246;76;4m⣤[38;2;21;2;0m [38;2;9;0;0m [38;2;8;0;0m [38;2;10;0;0m [38;2;246;62;0m⠈[38;2;255;80;3m⠻[38;2;255;87;5m⠿[38;2;255;90;5m⠿[38;2;255;66;5m⠖[38;2;8;0;0m  [38;2;241;64;0m⠈[38;2;225;75;0m⠉[38;2;236;71;0m⠉[38;2;250;66;0m⠉[38;2;241;69;0m⠉[38;2;238;70;0m⠉[38;2;237;64;0m⠁[38;2;194;115;2m⠻[38;2;255;177;5m⣿[38;2;255;197;6m⣿[38;2;255;199;6m⣿[38;2;211;145;5m⠿[38;2;10;0;0m [38;2;9;0;0m [38;2;10;0;0m [38;2;8;0;0m [38;2;253;61;0m⠉[38;2;255;82;3m⠻[38;2;245;69;0m⠉[38;2;255;59;0m⠁[38;2;13;0;0m [38;2;255;48;0m⢠[38;2;252;75;4m⡴[38;2;238;75;4m⠋[38;2;255;48;0m⠁[38;2;7;0;0m       [38;2;8;0;0m [38;2;7;0;0m [38;2;8;0;0m
[38;2;7;0;0m [38;2;8;0;0m [38;2;10;0;0m [38;2;7;0;0m    [38;2;8;0;0m    [38;2;7;0;0m [38;2;8;0;0m [38;2;15;1;0m [38;2;238;75;4m⠛[38;2;20;3;0m [38;2;255;65;0m⡄[38;2;8;0;0m [38;2;14;1;0m [38;2;9;0;0m [38;2;8;0;0m  [38;2;9;0;0m [38;2;8;0;0m  [38;2;9;0;0m  [38;2;255;58;5m⠴[38;2;12;0;0m [38;2;8;0;0m   [38;2;9;0;0m [38;2;13;1;0m [38;2;16;2;0m [38;2;15;2;0m [38;2;9;0;0m [38;2;8;0;0m [38;2;9;0;0m [38;2;8;0;0m  [38;2;16;1;0m [38;2;14;1;0m [38;2;255;54;5m⠤[38;2;16;1;0m [38;2;255;61;0m⠃[38;2;8;0;0m [38;2;9;0;0m [38;2;7;0;0m [38;2;8;0;0m    [38;2;7;0;0m [38;2;253;66;0m⣀[38;2;16;2;0m [38;2;7;0;0m   [38;2;8;0;0m
[38;2;15;2;0m [38;2;255;71;3m⢼[38;2;255;84;5m⣷[38;2;251;64;0m⠄[38;2;6;0;0m [38;2;7;0;0m [38;2;6;0;0m [38;2;7;0;0m    [38;2;6;0;0m [38;2;7;0;0m  [38;2;8;0;0m [38;2;7;0;0m [38;2;8;0;0m [38;2;9;0;0m [38;2;255;67;5m⠛[38;2;14;1;0m [38;2;255;56;0m⠴[38;2;10;0;0m [38;2;255;59;0m⣀[38;2;255;56;0m⡀[38;2;8;0;0m [38;2;11;0;0m [38;2;8;0;0m    [38;2;9;0;0m  [38;2;8;0;0m [38;2;11;0;0m [38;2;9;0;0m [38;2;12;0;0m [38;2;255;58;5m⣀[38;2;255;51;0m⡀[38;2;255;46;0m⠠[38;2;255;45;0m⠄[38;2;8;0;0m [38;2;255;52;0m⠈[38;2;14;1;0m [38;2;7;0;0m    [38;2;8;0;0m [38;2;7;0;0m    [38;2;6;0;0m [38;2;7;0;0m [38;2;255;47;0m⠈[38;2;10;0;0m [38;2;7;0;0m [38;2;8;0;0m [38;2;7;0;0m [38;2;8;0;0m
[38;2;6;0;0m [38;2;11;1;0m [38;2;255;55;0m⠁[38;2;6;0;0m         [38;2;7;0;0m   [38;2;6;0;0m [38;2;7;0;0m   [38;2;8;0;0m [38;2;7;0;0m [38;2;6;0;0m [38;2;255;45;0m⠈[38;2;16;2;0m [38;2;7;0;0m [38;2;255;64;0m⠛[38;2;18;2;0m [38;2;11;0;0m [38;2;255;64;4m⠛[38;2;255;54;0m⠃[38;2;255;41;0m⠈[38;2;255;57;0m⠃[38;2;7;0;0m [38;2;255;55;0m⠘[38;2;17;2;0m [38;2;9;0;0m [38;2;19;2;0m [38;2;15;1;0m [38;2;8;0;0m  [38;2;7;0;0m [38;2;8;0;0m [38;2;7;0;0m [38;2;6;0;0m [38;2;8;0;0m [38;2;7;0;0m  [38;2;8;0;0m [38;2;7;0;0m [38;2;6;0;0m [38;2;7;0;0m  [38;2;6;0;0m [38;2;7;0;0m  [38;2;8;0;0m  [38;2;7;0;0m [38;2;8;0;0m [38;2;7;0;0m [0m
`

// Color schemes for displaying data (metrics and system metrics) on the charts.
//
// Each scheme consists of an ordered list of colors,
// where each new graph, and/or a line on a multi-line graph takes the next color.
// Colors get reused in a cyclic manner.
var colorSchemes = map[string][]compat.AdaptiveColor{
	"sunset-glow": { // Golden-pink gradient
		compat.AdaptiveColor{Light: lipgloss.Color("#B84FD4"), Dark: lipgloss.Color("#E281FE")},
		compat.AdaptiveColor{Light: lipgloss.Color("#BD5AB9"), Dark: lipgloss.Color("#E78DE3")},
		compat.AdaptiveColor{Light: lipgloss.Color("#BF60AB"), Dark: lipgloss.Color("#E993D5")},
		compat.AdaptiveColor{Light: lipgloss.Color("#C36C91"), Dark: lipgloss.Color("#ED9FBB")},
		compat.AdaptiveColor{Light: lipgloss.Color("#C67283"), Dark: lipgloss.Color("#F0A5AD")},
		compat.AdaptiveColor{Light: lipgloss.Color("#C87875"), Dark: lipgloss.Color("#F2AB9F")},
		compat.AdaptiveColor{Light: lipgloss.Color("#CC8451"), Dark: lipgloss.Color("#F6B784")},
		compat.AdaptiveColor{Light: lipgloss.Color("#CE8A45"), Dark: lipgloss.Color("#F8BD78")},
		compat.AdaptiveColor{Light: lipgloss.Color("#D19038"), Dark: lipgloss.Color("#FBC36B")},
		compat.AdaptiveColor{Light: lipgloss.Color("#D59C1C"), Dark: lipgloss.Color("#FFCF4F")},
	},
	"blush-tide": { // Pink-teal gradient
		compat.AdaptiveColor{Light: lipgloss.Color("#D94F8C"), Dark: lipgloss.Color("#F9A7CC")},
		compat.AdaptiveColor{Light: lipgloss.Color("#CA60AC"), Dark: lipgloss.Color("#EEB3E0")},
		compat.AdaptiveColor{Light: lipgloss.Color("#B96FC4"), Dark: lipgloss.Color("#E4BFEE")},
		compat.AdaptiveColor{Light: lipgloss.Color("#A77DD4"), Dark: lipgloss.Color("#DBC9F7")},
		compat.AdaptiveColor{Light: lipgloss.Color("#9489DF"), Dark: lipgloss.Color("#D5D3FC")},
		compat.AdaptiveColor{Light: lipgloss.Color("#8095E5"), Dark: lipgloss.Color("#D1DCFE")},
		compat.AdaptiveColor{Light: lipgloss.Color("#6AA1E6"), Dark: lipgloss.Color("#D0E5FF")},
		compat.AdaptiveColor{Light: lipgloss.Color("#50ACE2"), Dark: lipgloss.Color("#D3ECFE")},
		compat.AdaptiveColor{Light: lipgloss.Color("#33B6D9"), Dark: lipgloss.Color("#D8F2FC")},
		compat.AdaptiveColor{
			Light: lipgloss.Color("#10BFCC"), Dark: lipgloss.Color("#E1F7FA")}, // == teal450
	},
	"gilded-lagoon": { // Golden-teal gradient
		compat.AdaptiveColor{Light: lipgloss.Color("#D59C1C"), Dark: lipgloss.Color("#FFCF4F")},
		compat.AdaptiveColor{Light: lipgloss.Color("#C2A636"), Dark: lipgloss.Color("#EADB74")},
		compat.AdaptiveColor{Light: lipgloss.Color("#AFAD4C"), Dark: lipgloss.Color("#DAE492")},
		compat.AdaptiveColor{Light: lipgloss.Color("#9CB35F"), Dark: lipgloss.Color("#CFEBAB")},
		compat.AdaptiveColor{Light: lipgloss.Color("#8AB872"), Dark: lipgloss.Color("#C8EFC0")},
		compat.AdaptiveColor{Light: lipgloss.Color("#77BB83"), Dark: lipgloss.Color("#C5F3D2")},
		compat.AdaptiveColor{Light: lipgloss.Color("#62BE95"), Dark: lipgloss.Color("#C7F5E1")},
		compat.AdaptiveColor{Light: lipgloss.Color("#4CBFA6"), Dark: lipgloss.Color("#CDF6ED")},
		compat.AdaptiveColor{Light: lipgloss.Color("#32C0B9"), Dark: lipgloss.Color("#D5F7F5")},
		compat.AdaptiveColor{
			Light: lipgloss.Color("#10BFCC"), Dark: lipgloss.Color("#E1F7FA")}, // == teal450
	},
	"bootstrap-vibe": { // Badge-friendly palette with familiar utility tones
		compat.AdaptiveColor{Light: lipgloss.Color("#6c757d"), Dark: lipgloss.Color("#a7b0b8")},
		compat.AdaptiveColor{Light: lipgloss.Color("#0d6efd"), Dark: lipgloss.Color("#78aefc")},
		compat.AdaptiveColor{Light: lipgloss.Color("#198754"), Dark: lipgloss.Color("#72cf9d")},
		compat.AdaptiveColor{Light: lipgloss.Color("#0dcaf0"), Dark: lipgloss.Color("#7be3fa")},
		compat.AdaptiveColor{Light: lipgloss.Color("#fd7e14"), Dark: lipgloss.Color("#ffb574")},
		compat.AdaptiveColor{Light: lipgloss.Color("#dc3545"), Dark: lipgloss.Color("#f28a93")},
		compat.AdaptiveColor{Light: lipgloss.Color("#6f42c1"), Dark: lipgloss.Color("#b99aff")},
		compat.AdaptiveColor{Light: lipgloss.Color("#20c997"), Dark: lipgloss.Color("#83e6ca")},
	},
	"wandb-vibe-10": {
		compat.AdaptiveColor{Light: lipgloss.Color("#8A8D91"), Dark: lipgloss.Color("#B1B4B9")},
		compat.AdaptiveColor{Light: lipgloss.Color("#3DBAC4"), Dark: lipgloss.Color("#58D3DB")},
		compat.AdaptiveColor{Light: lipgloss.Color("#42B88A"), Dark: lipgloss.Color("#5ED6A4")},
		compat.AdaptiveColor{Light: lipgloss.Color("#E07040"), Dark: lipgloss.Color("#FCA36F")},
		compat.AdaptiveColor{Light: lipgloss.Color("#E85565"), Dark: lipgloss.Color("#FF7A88")},
		compat.AdaptiveColor{Light: lipgloss.Color("#5A96E0"), Dark: lipgloss.Color("#7DB1FA")},
		compat.AdaptiveColor{Light: lipgloss.Color("#9AC24A"), Dark: lipgloss.Color("#BBE06B")},
		compat.AdaptiveColor{Light: lipgloss.Color("#E0AD20"), Dark: lipgloss.Color("#FFCF4D")},
		compat.AdaptiveColor{Light: lipgloss.Color("#C85EE8"), Dark: lipgloss.Color("#E180FF")},
		compat.AdaptiveColor{Light: lipgloss.Color("#9475E8"), Dark: lipgloss.Color("#B199FF")},
	},
	"wandb-vibe-20": {
		compat.AdaptiveColor{Light: lipgloss.Color("#AEAFB3"), Dark: lipgloss.Color("#D4D5D9")},
		compat.AdaptiveColor{Light: lipgloss.Color("#454B54"), Dark: lipgloss.Color("#565C66")},
		compat.AdaptiveColor{Light: lipgloss.Color("#7AD4DB"), Dark: lipgloss.Color("#A9EDF2")},
		compat.AdaptiveColor{Light: lipgloss.Color("#04707F"), Dark: lipgloss.Color("#038194")},
		compat.AdaptiveColor{Light: lipgloss.Color("#6DDBA8"), Dark: lipgloss.Color("#A1F0CB")},
		compat.AdaptiveColor{Light: lipgloss.Color("#00704A"), Dark: lipgloss.Color("#00875A")},
		compat.AdaptiveColor{Light: lipgloss.Color("#EAB08A"), Dark: lipgloss.Color("#FFCFB2")},
		compat.AdaptiveColor{Light: lipgloss.Color("#A84728"), Dark: lipgloss.Color("#C2562F")},
		compat.AdaptiveColor{Light: lipgloss.Color("#EAA0A5"), Dark: lipgloss.Color("#FFC7CA")},
		compat.AdaptiveColor{Light: lipgloss.Color("#B82038"), Dark: lipgloss.Color("#CC2944")},
		compat.AdaptiveColor{Light: lipgloss.Color("#8FBDE8"), Dark: lipgloss.Color("#BDD9FF")},
		compat.AdaptiveColor{Light: lipgloss.Color("#2850A8"), Dark: lipgloss.Color("#1F59C4")},
		compat.AdaptiveColor{Light: lipgloss.Color("#B0D470"), Dark: lipgloss.Color("#D0ED9D")},
		compat.AdaptiveColor{Light: lipgloss.Color("#4E7424"), Dark: lipgloss.Color("#5F8A2D")},
		compat.AdaptiveColor{Light: lipgloss.Color("#EAC860"), Dark: lipgloss.Color("#FFE49E")},
		compat.AdaptiveColor{Light: lipgloss.Color("#9A5E10"), Dark: lipgloss.Color("#B8740F")},
		compat.AdaptiveColor{Light: lipgloss.Color("#D99DE8"), Dark: lipgloss.Color("#EFC2FC")},
		compat.AdaptiveColor{Light: lipgloss.Color("#8528A8"), Dark: lipgloss.Color("#9E36C2")},
		compat.AdaptiveColor{Light: lipgloss.Color("#B8A8E8"), Dark: lipgloss.Color("#D6C9FF")},
		compat.AdaptiveColor{Light: lipgloss.Color("#5538B0"), Dark: lipgloss.Color("#6645D1")},
	},
}

// GraphColors returns the palette for the requested scheme.
//
// If the scheme is unknown, it falls back to DefaultColorScheme.
func GraphColors(scheme string) []compat.AdaptiveColor {
	if colors, ok := colorSchemes[scheme]; ok {
		return colors
	}
	return colorSchemes[DefaultColorScheme]
}

// Metrics grid styles.
var (
	headerStyle = lipgloss.NewStyle().Bold(true).Foreground(colorSubheading)

	navInfoStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	headerContainerStyle = lipgloss.NewStyle().MarginLeft(1).MarginTop(0).MarginBottom(0)

	gridContainerStyle = lipgloss.NewStyle().MarginLeft(1).MarginRight(1)
)

// Chart styles.
var (
	borderStyle = lipgloss.NewStyle().
			BorderStyle(lipgloss.RoundedBorder()).
			BorderForeground(colorLayout)

	titleStyle = lipgloss.NewStyle().Foreground(colorAccent).Bold(true)

	seriesCountStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	focusedBorderStyle = borderStyle.BorderForeground(colorLayoutHighlight)

	axisStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	labelStyle = lipgloss.NewStyle().Foreground(colorText)

	inspectionLineStyle = lipgloss.NewStyle().Foreground(colorSubtle)

	inspectionLegendStyle = lipgloss.NewStyle().
				Foreground(compat.AdaptiveColor{
			Light: lipgloss.Color("#111111"),
			Dark:  lipgloss.Color("#EEEEEE"),
		}).
		Background(compat.AdaptiveColor{
			Light: lipgloss.Color("#EEEEEE"),
			Dark:  lipgloss.Color("#333333"),
		})
)

// Status bar styles.
var (
	statusBarStyle = lipgloss.NewStyle().
		Foreground(moon900).
		Background(colorLayoutHighlight).
		Padding(0, StatusBarPadding)
)

var errorStyle = lipgloss.NewStyle()

// runOverviewTagLightText is the default (white) foreground for tag badges
// when the background is too dark for dark text to be legible.
var runOverviewTagLightText = lipgloss.Color("#ffffff")

// runOverviewTagBackgroundColor returns the background color for a tag badge.
// It deterministically maps tag to a color in the given scheme so that the
// same tag always gets the same color.
func runOverviewTagBackgroundColor(scheme, tag string) compat.AdaptiveColor {
	colors := GraphColors(scheme)
	return colors[colorIndex(tag, len(colors))]
}

// runOverviewTagForegroundColor picks a foreground color (light or dark) for
// each adaptive variant of bg that satisfies WCAG contrast requirements.
func runOverviewTagForegroundColor(bg compat.AdaptiveColor) compat.AdaptiveColor {
	return compat.AdaptiveColor{
		Light: runOverviewTagTextColor(bg.Light),
		Dark:  runOverviewTagTextColor(bg.Dark),
	}
}

// runOverviewTagTextColor returns white or dark text for a single background
// color, choosing whichever yields the higher WCAG contrast ratio.
func runOverviewTagTextColor(bg any) color.Color {
	r, g, b, ok := parseHexColor(fmt.Sprint(bg))
	if !ok {
		return runOverviewTagLightText
	}

	lightContrast := contrastRatioRGB(r, g, b, 0xff, 0xff, 0xff)
	darkContrast := contrastRatioRGB(r, g, b, 0x17, 0x17, 0x17)
	if darkContrast >= lightContrast {
		return colorDark
	}

	return runOverviewTagLightText
}

// parseHexColor extracts 8-bit RGB components from a "#RRGGBB" hex string.
// It returns false if hex is not in the expected format.
func parseHexColor(hex string) (uint8, uint8, uint8, bool) {
	var r, g, b uint8
	if _, err := fmt.Sscanf(hex, "#%02x%02x%02x", &r, &g, &b); err != nil {
		return 0, 0, 0, false
	}
	return r, g, b, true
}

// contrastRatioRGB computes the WCAG 2.x contrast ratio between two RGB colors.
// The returned value ranges from 1 (identical) to 21 (black vs white).
func contrastRatioRGB(r1, g1, b1, r2, g2, b2 uint8) float64 {
	l1 := relativeLuminance(r1, g1, b1)
	l2 := relativeLuminance(r2, g2, b2)
	if l1 < l2 {
		l1, l2 = l2, l1
	}
	return (l1 + 0.05) / (l2 + 0.05)
}

// relativeLuminance returns the WCAG relative luminance of an sRGB color.
// See https://www.w3.org/TR/WCAG21/#dfn-relative-luminance.
//
// Note: WCAG = Web Content Accessibility Guidelines.
func relativeLuminance(r, g, b uint8) float64 {
	return 0.2126*srgbToLinear(r) + 0.7152*srgbToLinear(g) + 0.0722*srgbToLinear(b)
}

// srgbToLinear converts a single 8-bit sRGB channel value to linear-light
// using the IEC 61966-2-1 transfer function.
func srgbToLinear(c uint8) float64 {
	v := float64(c) / 255.0
	if v <= 0.04045 {
		return v / 12.92
	}
	return math.Pow((v+0.055)/1.055, 2.4)
}

// runOverviewTagStyle returns the complete lipgloss badge style for a tag.
// The background is derived from the color scheme and the foreground is
// automatically chosen (light or dark) to ensure readable contrast.
func runOverviewTagStyle(scheme, tag string) lipgloss.Style {
	bg := runOverviewTagBackgroundColor(scheme, tag)
	fg := runOverviewTagForegroundColor(bg)
	return lipgloss.NewStyle().
		Foreground(fg).
		Background(bg).
		Padding(0, 1).
		Bold(true)
}

// Run overview styles.
var (
	runOverviewSidebarSectionHeaderStyle = lipgloss.
						NewStyle().Bold(true).Foreground(colorSubheading)
	runOverviewSidebarSectionStyle    = lipgloss.NewStyle().Foreground(colorText).Bold(true)
	runOverviewSidebarKeyStyle        = lipgloss.NewStyle().Foreground(colorItemKey)
	runOverviewSidebarValueStyle      = lipgloss.NewStyle().Foreground(colorItemValue)
	runOverviewSidebarHighlightedItem = lipgloss.NewStyle().
						Foreground(colorDark).Background(colorSelected)
)

// Left sidebar styles.
var (
	leftSidebarStyle       = lipgloss.NewStyle().Padding(0, 1)
	leftSidebarBorderStyle = lipgloss.NewStyle().
				Border(RightBorder).
				BorderForeground(colorLayout).
				BorderTop(false)
	leftSidebarHeaderStyle = lipgloss.NewStyle().
				Bold(true).
				Foreground(colorSubheading).
				MarginBottom(0)
	RightBorder = lipgloss.Border{
		Top:         string(unicodeSpace),
		Bottom:      string(unicodeSpace),
		Left:        "",
		Right:       string(boxLightVertical),
		TopLeft:     string(unicodeSpace),
		TopRight:    string(unicodeSpace),
		BottomLeft:  string(unicodeSpace),
		BottomRight: string(unicodeSpace),
	}
)

// Right sidebar styles.
var (
	rightSidebarStyle       = lipgloss.NewStyle().PaddingLeft(1)
	rightSidebarBorderStyle = lipgloss.NewStyle().
				Border(LeftBorder).
				BorderForeground(colorLayout).
				BorderTop(false)
	rightSidebarHeaderStyle = lipgloss.NewStyle().
				Bold(true).
				Foreground(colorSubheading).
				MarginLeft(0)
	LeftBorder = lipgloss.Border{
		Top:         string(unicodeSpace),
		Bottom:      string(unicodeSpace),
		Left:        string(boxLightVertical),
		Right:       "",
		TopLeft:     string(unicodeSpace),
		TopRight:    string(unicodeSpace),
		BottomLeft:  string(unicodeSpace),
		BottomRight: string(unicodeSpace),
	}
)

// Console logs pane styles.
var (
	consoleLogsPaneBorderStyle = lipgloss.NewStyle().
					Border(topOnlyBorder).
					BorderForeground(colorLayout).
					BorderTop(true).
					BorderBottom(false).
					BorderLeft(false).
					BorderRight(false).
					PaddingBottom(1)

	consoleLogsPaneHeaderStyle = lipgloss.NewStyle().
					Bold(true).
					Foreground(colorSubheading).
					PaddingLeft(1)

	consoleLogsPaneTimestampStyle = lipgloss.NewStyle().
					Foreground(colorSubtle).
					PaddingLeft(1)

	consoleLogsPaneValueStyle = lipgloss.NewStyle().
					Foreground(colorItemValue)

	consoleLogsPaneHighlightedTimestampStyle = lipgloss.NewStyle().
							Background(colorSelected).
							Foreground(colorDark).
							PaddingLeft(1)

	consoleLogsPaneHighlightedValueStyle = lipgloss.NewStyle().
						Background(colorSelected).
						Foreground(colorDark)

	// topOnlyBorder draws a single horizontal line at the top of the box.
	topOnlyBorder = lipgloss.Border{
		Top:         string(unicodeEmDash),
		Bottom:      "",
		Left:        "",
		Right:       "",
		TopLeft:     string(unicodeEmDash),
		TopRight:    string(unicodeEmDash),
		BottomLeft:  "",
		BottomRight: "",
	}
)

// AnimationDuration is the duration for sidebar animations.
const AnimationDuration = 150 * time.Millisecond

// AnimationSteps is the number of steps in sidebar animations.
const AnimationSteps = 10

// AnimationFrame is the tick interval used for sidebar animations.
const AnimationFrame = AnimationDuration / AnimationSteps

// Help screen styles.
var (
	helpKeyStyle = lipgloss.NewStyle().Bold(true).Foreground(colorSubheading).Width(24)

	helpDescStyle = lipgloss.NewStyle().Foreground(colorText)

	helpSectionStyle = lipgloss.NewStyle().Bold(true).Foreground(colorHeading)

	helpContentStyle = lipgloss.NewStyle().MarginLeft(2).MarginTop(1)
)

// Workspace view mode styles.
var (
	workspaceTopMarginLines = 1
	workspaceHeaderLines    = 1
	runsSidebarBorderCols   = 2

	colorSelectedRunInactiveStyle = compat.AdaptiveColor{
		Light: lipgloss.Color("#F5D28A"),
		Dark:  lipgloss.Color("#6B5200"),
	}

	evenRunStyle             = lipgloss.NewStyle()
	oddRunStyle              = lipgloss.NewStyle().Background(getOddRunStyleColor())
	selectedRunStyle         = lipgloss.NewStyle().Background(colorSelected)
	selectedRunInactiveStyle = lipgloss.NewStyle().Background(colorSelectedRunInactiveStyle)
)
