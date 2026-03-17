package leet

import (
	"strings"
	"sync"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
)

type brandArtPreset string

const (
	brandArtPresetClassic    brandArtPreset = "classic" // This is also good.
	brandArtPresetLagoon     brandArtPreset = "lagoon"
	brandArtPresetSplitBrand brandArtPreset = "split-brand" // I like this the most?
	brandArtPresetGoldBrand  brandArtPreset = "gold"
	brandArtPresetTealBrand  brandArtPreset = "teal"
	brandArtPresetAurora     brandArtPreset = "aurora"

	defaultBrandArtPreset = brandArtPresetGoldBrand

	brandArtInlineGap  = 3
	brandArtStackedGap = 1
)

const (
	brandArtShadowOffset = 1
)

type brandArtCellKind uint8

const (
	brandArtCellEmpty brandArtCellKind = iota
	brandArtCellGlyph
	brandArtCellShadow
)

type brandArtCell struct {
	glyph rune
	kind  brandArtCellKind
}

type brandArtPalette []compat.AdaptiveColor

type brandArtPresetConfig struct {
	Wandb brandArtPalette
	Leet  brandArtPalette
}

type brandArtBlock struct {
	lines  []string
	width  int
	height int
}

func brandAdaptiveColor(light, dark string) compat.AdaptiveColor {
	return compat.AdaptiveColor{
		Light: lipgloss.Color(light),
		Dark:  lipgloss.Color(dark),
	}
}

var (
	brandArtClassicPalette = brandArtPalette{
		{
			Light: wandbColor,
			Dark:  wandbColor,
		},
	}

	brandArtGoldPalette = brandArtPalette{
		brandAdaptiveColor("#A56A00", "#FFCA4D"),
		brandAdaptiveColor("#C18200", "#FFD866"),
		brandAdaptiveColor("#D39212", "#FFE082"),
		brandAdaptiveColor("#E7B24C", "#FFF0B8"),
	}

	brandArtTealPalette = brandArtPalette{
		brandAdaptiveColor("#0A7280", "#6FD9E3"),
		brandAdaptiveColor("#0E8996", "#89E4EB"),
		brandAdaptiveColor("#0FA5B1", "#B7F1F5"),
		brandAdaptiveColor("#10BFCC", "#E1F7FA"),
	}

	brandArtLagoonPalette = brandArtPalette{
		brandAdaptiveColor("#A56A00", "#FFCA4D"),
		brandAdaptiveColor("#C18200", "#FFD866"),
		brandAdaptiveColor("#9DAE47", "#DAE492"),
		brandAdaptiveColor("#4CBFA6", "#CDF6ED"),
		brandAdaptiveColor("#10BFCC", "#E1F7FA"),
	}

	brandArtAuroraPalette = brandArtPalette{
		brandAdaptiveColor("#8A35C9", "#E8A7FF"),
		brandAdaptiveColor("#6F53D8", "#D8C3FF"),
		brandAdaptiveColor("#4E75E0", "#B7D7FF"),
		brandAdaptiveColor("#10BFCC", "#D8FAFF"),
	}

	brandArtPresets = map[brandArtPreset]brandArtPresetConfig{
		brandArtPresetClassic: {
			Wandb: brandArtClassicPalette,
			Leet:  brandArtClassicPalette,
		},
		brandArtPresetLagoon: {
			Wandb: brandArtLagoonPalette,
			Leet:  brandArtLagoonPalette,
		},
		brandArtPresetSplitBrand: {
			Wandb: brandArtGoldPalette,
			Leet:  brandArtTealPalette,
		},
		brandArtPresetGoldBrand: {
			Wandb: brandArtGoldPalette,
			Leet:  brandArtGoldPalette,
		},
		brandArtPresetTealBrand: {
			Wandb: brandArtTealPalette,
			Leet:  brandArtTealPalette,
		},
		brandArtPresetAurora: {
			Wandb: brandArtAuroraPalette,
			Leet:  brandArtAuroraPalette,
		},
	}

	brandArtWandbBlock = newBrandArtBlock(wandbArt)
	brandArtLeetBlock  = newBrandArtBlock(leetArt)

	brandArtInlineOnce = sync.OnceValue(func() string {
		return renderBrandArtLayout(defaultBrandArtPreset, true)
	})
	brandArtStackedOnce = sync.OnceValue(func() string {
		return renderBrandArtLayout(defaultBrandArtPreset, false)
	})
)

// renderBrandArtForWidth chooses the inline form when it fits and falls back
// to the stacked form for narrower panes.
func renderBrandArtForWidth(width int) string {
	if width > 0 && width < brandArtInlineWidth() {
		return brandArtStackedOnce()
	}
	return brandArtInlineOnce()
}

func brandArtInlineWidth() int {
	return brandArtRenderedWidth(brandArtWandbBlock) +
		brandArtInlineGap +
		brandArtRenderedWidth(brandArtLeetBlock)
}

func brandArtRenderedWidth(block brandArtBlock) int {
	return block.width + brandArtShadowOffset
}
func newBrandArtBlock(raw string) brandArtBlock {
	lines := strings.Split(strings.Trim(raw, "\n"), "\n")

	width := 0
	for _, line := range lines {
		width = max(width, lipgloss.Width(line))
	}

	padded := make([]string, len(lines))
	for i, line := range lines {
		padding := max(width-lipgloss.Width(line), 0)
		padded[i] = line + strings.Repeat(" ", padding)
	}

	return brandArtBlock{
		lines:  padded,
		width:  width,
		height: len(padded),
	}
}

func renderBrandArtLayout(preset brandArtPreset, inline bool) string {
	cfg, ok := brandArtPresets[preset]
	if !ok {
		cfg = brandArtPresets[brandArtPresetSplitBrand]
	}

	wandb := renderBrandArtBlock(brandArtWandbBlock, cfg.Wandb)
	leet := renderBrandArtBlock(brandArtLeetBlock, cfg.Leet)

	if inline {
		return joinBrandArtHorizontal(
			wandb,
			brandArtRenderedWidth(brandArtWandbBlock),
			leet,
			brandArtRenderedWidth(brandArtLeetBlock),
			brandArtInlineGap,
		)
	}

	parts := []string{wandb}
	for range brandArtStackedGap {
		parts = append(parts, "")
	}
	parts = append(parts, leet)

	return lipgloss.JoinVertical(lipgloss.Center, parts...)
}

func renderBrandArtBlock(block brandArtBlock, palette brandArtPalette) string {
	if len(palette) == 0 {
		palette = brandArtClassicPalette
	}

	styles := make([]lipgloss.Style, len(palette))
	for i, color := range palette {
		styles[i] = lipgloss.NewStyle().
			Foreground(color).
			Bold(true)
	}

	shadowStyle := lipgloss.NewStyle().Foreground(getShadowStyleColor())

	width := block.width + brandArtShadowOffset
	height := block.height + brandArtShadowOffset

	cells := make([][]brandArtCell, height)
	for y := range cells {
		cells[y] = make([]brandArtCell, width)
	}

	for y, line := range block.lines {
		x := 0
		for _, r := range line {
			if r != ' ' {
				cells[y][x] = brandArtCell{
					glyph: r,
					kind:  brandArtCellGlyph,
				}
			}
			x++
		}
	}

	for y := 0; y < block.height; y++ {
		for x := 0; x < block.width; x++ {
			if cells[y][x].kind != brandArtCellGlyph {
				continue
			}
			sx, sy := x+brandArtShadowOffset, y+brandArtShadowOffset
			if cells[sy][sx].kind != brandArtCellEmpty {
				continue
			}
			cells[sy][sx] = brandArtCell{
				glyph: cells[y][x].glyph,
				kind:  brandArtCellShadow,
			}
		}
	}

	var out strings.Builder
	for y, row := range cells {
		for x, cell := range row {
			switch cell.kind {
			case brandArtCellGlyph:
				idx := brandArtPaletteIndex(x, block.width, len(styles))
				out.WriteString(styles[idx].Render(string(cell.glyph)))
			case brandArtCellShadow:
				out.WriteString(shadowStyle.Render(string(cell.glyph)))
			default:
				out.WriteByte(' ')
			}
		}

		if y < len(cells)-1 {
			out.WriteByte('\n')
		}
	}

	return out.String()
}

func brandArtPaletteIndex(x, width, paletteSize int) int {
	if paletteSize <= 1 || width <= 1 {
		return 0
	}
	return x * (paletteSize - 1) / (width - 1)
}

func joinBrandArtHorizontal(
	left string,
	leftWidth int,
	right string,
	rightWidth int,
	gap int,
) string {
	leftLines := strings.Split(left, "\n")
	rightLines := strings.Split(right, "\n")
	height := max(len(leftLines), len(rightLines))

	leftBlank := strings.Repeat(" ", leftWidth)
	rightBlank := strings.Repeat(" ", rightWidth)
	spacer := strings.Repeat(" ", gap)

	out := make([]string, 0, height)
	for i := 0; i < height; i++ {
		l := leftBlank
		r := rightBlank

		if i < len(leftLines) {
			l = leftLines[i]
		}
		if i < len(rightLines) {
			r = rightLines[i]
		}

		out = append(out, l+spacer+r)
	}

	return strings.Join(out, "\n")
}
