package leet

import (
	"fmt"
	"os"
	"sync"
	"time"

	"github.com/charmbracelet/lipgloss"
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
			_, err := fmt.Sscanf(string(rgb), "#%02x%02x%02x", &r, &g, &b)
			if err == nil {
				termBgR, termBgG, termBgB = r, g, b
				termBgDetected = true
			}
		}
	})
}

// blendRGB blends (r,g,b) toward (tr,tg,tb) by alpha (0.0–1.0).
func blendRGB(r, g, b, tr, tg, tb uint8, alpha float64) lipgloss.Color {
	blend := func(base, target uint8) uint8 {
		return uint8(float64(base)*(1-alpha) + float64(target)*alpha)
	}
	return lipgloss.Color(fmt.Sprintf("#%02x%02x%02x",
		blend(r, tr), blend(g, tg), blend(b, tb),
	))
}

// getOddRunStyleColor returns a color 5% darker than the terminal background.
func getOddRunStyleColor() lipgloss.TerminalColor {
	initTerminalBg()

	if termBgDetected {
		return blendRGB(termBgR, termBgG, termBgB, 128, 128, 128, 0.05)
	}

	return lipgloss.AdaptiveColor{
		Light: "#d0d0d0",
		Dark:  "#1c1c1c",
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
	DefaultMetricsGridRows = 4
	DefaultMetricsGridCols = 3
	DefaultSystemGridRows  = 6
	DefaultSystemGridCols  = 2
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

	// unicodeSpace is the regular whitespace.
	unicodeSpace rune = '\u0020'

	// mediumShadeBlock is a medium-shaded block.
	mediumShadeBlock rune = '\u2592' // ▒
)

// WANDB brand colors.
const (
	// Primary colors.
	moon900    = lipgloss.Color("#171A1F")
	wandbColor = lipgloss.Color("#FCBC32")
)

// Secondary colors.
var teal450 = lipgloss.AdaptiveColor{
	Light: "#10BFCC",
	Dark:  "#E1F7FA",
}

// Functional colors not specific to any visual component.
var (
	// Color for main items such as chart titles.
	colorAccent = lipgloss.AdaptiveColor{
		Light: "#6c6c6c",
		Dark:  "#bcbcbc",
	}

	// Main text color that appears the most frequently on the screen.
	colorText = lipgloss.AdaptiveColor{
		Light: "#8a8a8a", // ANSI color 245
		Dark:  "#8a8a8a",
	}

	// Color for extra or parenthetical text or information.
	// Axis lines in charts.
	colorSubtle = lipgloss.AdaptiveColor{
		Light: "#585858", // ANSI color 240
		Dark:  "#585858",
	}

	// Color for layout elements, like borders and separator lines.
	colorLayout = lipgloss.AdaptiveColor{
		Light: "#949494",
		Dark:  "#444444",
	}

	colorDark = lipgloss.Color("#171717")

	// Color for layout elements when they're highlighted or focused.
	colorLayoutHighlight = teal450

	// Color for top-level headings; least frequent.
	// Leet logo, help page section headings.
	colorHeading = wandbColor

	// Color for lower-level headings; more frequent than headings.
	// Help page keys, metrics grid header.
	colorSubheading = lipgloss.AdaptiveColor{
		Light: "#3a3a3a",
		Dark:  "#eeeeee",
	}

	// Colors for key-value pairs such as run summary or config items.
	colorItemKey   = lipgloss.Color("243")
	colorItemValue = lipgloss.AdaptiveColor{
		Light: "#262626",
		Dark:  "#d0d0d0",
	}
	colorSelected = lipgloss.AdaptiveColor{
		Light: "#c6c6c6",
		Dark:  "#444444",
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
var colorSchemes = map[string][]lipgloss.AdaptiveColor{
	"sunset-glow": { // Golden-pink gradient
		lipgloss.AdaptiveColor{Light: "#B84FD4", Dark: "#E281FE"},
		lipgloss.AdaptiveColor{Light: "#BD5AB9", Dark: "#E78DE3"},
		lipgloss.AdaptiveColor{Light: "#BF60AB", Dark: "#E993D5"},
		lipgloss.AdaptiveColor{Light: "#C36C91", Dark: "#ED9FBB"},
		lipgloss.AdaptiveColor{Light: "#C67283", Dark: "#F0A5AD"},
		lipgloss.AdaptiveColor{Light: "#C87875", Dark: "#F2AB9F"},
		lipgloss.AdaptiveColor{Light: "#CC8451", Dark: "#F6B784"},
		lipgloss.AdaptiveColor{Light: "#CE8A45", Dark: "#F8BD78"},
		lipgloss.AdaptiveColor{Light: "#D19038", Dark: "#FBC36B"},
		lipgloss.AdaptiveColor{Light: "#D59C1C", Dark: "#FFCF4F"},
	},
	"blush-tide": { // Pink-teal gradient
		lipgloss.AdaptiveColor{Light: "#D94F8C", Dark: "#F9A7CC"},
		lipgloss.AdaptiveColor{Light: "#CA60AC", Dark: "#EEB3E0"},
		lipgloss.AdaptiveColor{Light: "#B96FC4", Dark: "#E4BFEE"},
		lipgloss.AdaptiveColor{Light: "#A77DD4", Dark: "#DBC9F7"},
		lipgloss.AdaptiveColor{Light: "#9489DF", Dark: "#D5D3FC"},
		lipgloss.AdaptiveColor{Light: "#8095E5", Dark: "#D1DCFE"},
		lipgloss.AdaptiveColor{Light: "#6AA1E6", Dark: "#D0E5FF"},
		lipgloss.AdaptiveColor{Light: "#50ACE2", Dark: "#D3ECFE"},
		lipgloss.AdaptiveColor{Light: "#33B6D9", Dark: "#D8F2FC"},
		lipgloss.AdaptiveColor{Light: "#10BFCC", Dark: "#E1F7FA"}, // == teal450
	},
	"gilded-lagoon": { // Golden-teal gradient
		lipgloss.AdaptiveColor{Light: "#D59C1C", Dark: "#FFCF4F"},
		lipgloss.AdaptiveColor{Light: "#C2A636", Dark: "#EADB74"},
		lipgloss.AdaptiveColor{Light: "#AFAD4C", Dark: "#DAE492"},
		lipgloss.AdaptiveColor{Light: "#9CB35F", Dark: "#CFEBAB"},
		lipgloss.AdaptiveColor{Light: "#8AB872", Dark: "#C8EFC0"},
		lipgloss.AdaptiveColor{Light: "#77BB83", Dark: "#C5F3D2"},
		lipgloss.AdaptiveColor{Light: "#62BE95", Dark: "#C7F5E1"},
		lipgloss.AdaptiveColor{Light: "#4CBFA6", Dark: "#CDF6ED"},
		lipgloss.AdaptiveColor{Light: "#32C0B9", Dark: "#D5F7F5"},
		lipgloss.AdaptiveColor{Light: "#10BFCC", Dark: "#E1F7FA"}, // == teal450
	},
	"wandb-vibe-10": {
		lipgloss.AdaptiveColor{Light: "#8A8D91", Dark: "#B1B4B9"},
		lipgloss.AdaptiveColor{Light: "#3DBAC4", Dark: "#58D3DB"},
		lipgloss.AdaptiveColor{Light: "#42B88A", Dark: "#5ED6A4"},
		lipgloss.AdaptiveColor{Light: "#E07040", Dark: "#FCA36F"},
		lipgloss.AdaptiveColor{Light: "#E85565", Dark: "#FF7A88"},
		lipgloss.AdaptiveColor{Light: "#5A96E0", Dark: "#7DB1FA"},
		lipgloss.AdaptiveColor{Light: "#9AC24A", Dark: "#BBE06B"},
		lipgloss.AdaptiveColor{Light: "#E0AD20", Dark: "#FFCF4D"},
		lipgloss.AdaptiveColor{Light: "#C85EE8", Dark: "#E180FF"},
		lipgloss.AdaptiveColor{Light: "#9475E8", Dark: "#B199FF"},
	},
	"wandb-vibe-20": {
		lipgloss.AdaptiveColor{Light: "#AEAFB3", Dark: "#D4D5D9"},
		lipgloss.AdaptiveColor{Light: "#454B54", Dark: "#565C66"},
		lipgloss.AdaptiveColor{Light: "#7AD4DB", Dark: "#A9EDF2"},
		lipgloss.AdaptiveColor{Light: "#04707F", Dark: "#038194"},
		lipgloss.AdaptiveColor{Light: "#6DDBA8", Dark: "#A1F0CB"},
		lipgloss.AdaptiveColor{Light: "#00704A", Dark: "#00875A"},
		lipgloss.AdaptiveColor{Light: "#EAB08A", Dark: "#FFCFB2"},
		lipgloss.AdaptiveColor{Light: "#A84728", Dark: "#C2562F"},
		lipgloss.AdaptiveColor{Light: "#EAA0A5", Dark: "#FFC7CA"},
		lipgloss.AdaptiveColor{Light: "#B82038", Dark: "#CC2944"},
		lipgloss.AdaptiveColor{Light: "#8FBDE8", Dark: "#BDD9FF"},
		lipgloss.AdaptiveColor{Light: "#2850A8", Dark: "#1F59C4"},
		lipgloss.AdaptiveColor{Light: "#B0D470", Dark: "#D0ED9D"},
		lipgloss.AdaptiveColor{Light: "#4E7424", Dark: "#5F8A2D"},
		lipgloss.AdaptiveColor{Light: "#EAC860", Dark: "#FFE49E"},
		lipgloss.AdaptiveColor{Light: "#9A5E10", Dark: "#B8740F"},
		lipgloss.AdaptiveColor{Light: "#D99DE8", Dark: "#EFC2FC"},
		lipgloss.AdaptiveColor{Light: "#8528A8", Dark: "#9E36C2"},
		lipgloss.AdaptiveColor{Light: "#B8A8E8", Dark: "#D6C9FF"},
		lipgloss.AdaptiveColor{Light: "#5538B0", Dark: "#6645D1"},
	},
}

// GraphColors returns the palette for the requested scheme.
//
// If the scheme is unknown, it falls back to DefaultColorScheme.
func GraphColors(scheme string) []lipgloss.AdaptiveColor {
	if colors, ok := colorSchemes[scheme]; ok {
		return colors
	}
	return colorSchemes[DefaultColorScheme]
}

var errorStyle = lipgloss.NewStyle()

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
				Foreground(lipgloss.AdaptiveColor{Light: "#111111", Dark: "#EEEEEE"}).
				Background(lipgloss.AdaptiveColor{Light: "#EEEEEE", Dark: "#333333"})
)

// Status bar styles.
var (
	statusBarStyle = lipgloss.NewStyle().
		Foreground(moon900).
		Background(colorLayoutHighlight).
		Padding(0, StatusBarPadding)
)

// Run overview styles.
var (
	runOverviewSidebarSectionHeaderStyle = lipgloss.
						NewStyle().Bold(true).Foreground(colorSubheading)
	runOverviewSidebarSectionStyle    = lipgloss.NewStyle().Foreground(colorText).Bold(true)
	runOverviewSidebarKeyStyle        = lipgloss.NewStyle().Foreground(colorItemKey)
	runOverviewSidebarValueStyle      = lipgloss.NewStyle().Foreground(colorItemValue)
	runOverviewSidebarHighlightedItem = lipgloss.NewStyle().
						Foreground(colorDark).Background(colorSelectedRunStyle)
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
	rightSidebarStyle       = lipgloss.NewStyle().Padding(0, 1)
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

	colorSelectedRunStyle = lipgloss.AdaptiveColor{
		Dark:  "#FCBC32",
		Light: "#FCBC32",
	}

	colorSelectedRunInactiveStyle = lipgloss.AdaptiveColor{
		Light: "#F5D28A",
		Dark:  "#6B5200",
	}

	evenRunStyle             = lipgloss.NewStyle()
	oddRunStyle              = lipgloss.NewStyle().Background(getOddRunStyleColor())
	selectedRunStyle         = lipgloss.NewStyle().Background(colorSelectedRunStyle)
	selectedRunInactiveStyle = lipgloss.NewStyle().Background(colorSelectedRunInactiveStyle)
)
