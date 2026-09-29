package picture

import (
	"bytes"
	"fmt"
	"image"
	"image/png"
	"os"
	"strings"
	"sync/atomic"

	"github.com/charmbracelet/x/ansi"
	"github.com/charmbracelet/x/ansi/kitty"
)

var tmuxPassthroughEnabled atomic.Bool

func init() {
	parseEnvOverrides()
}

func parseEnvOverrides() {
	// Parse tmux passthrough env override
	switch os.Getenv("NTCHARTS_TMUX_PASSTHROUGH") {
	case "1", "true", "on", "yes":
		tmuxPassthroughEnabled.Store(true)
	case "0", "false", "off", "no":
		tmuxPassthroughEnabled.Store(false)
	default:
		tmuxPassthroughEnabled.Store(os.Getenv("TMUX") != "")
	}

	// Parse Kitty capability env override
	switch os.Getenv("NTCHARTS_KITTY") {
	case "supported", "true", "1", "on", "yes":
		ForceKittyCapability(KittyCapabilitySupported)
	case "unsupported", "false", "0", "off", "no":
		ForceKittyCapability(KittyCapabilityUnsupported)
	}
}

// SetTmuxPassthrough enables or disables tmux passthrough wrapping. When enabled,
// Kitty graphics protocol sequences are wrapped in tmux's DCS passthrough sequence
// to allow them to render correctly when running inside tmux (with `allow-passthrough on` enabled).
//
// This is auto-enabled by default if the TMUX environment variable is set.
func SetTmuxPassthrough(enabled bool) {
	tmuxPassthroughEnabled.Store(enabled)
}

func tmuxWrap(seq string) string {
	if tmuxPassthroughEnabled.Load() {
		return ansi.TmuxPassthrough(seq)
	}
	return seq
}

// buildKittyAPC encodes img as a Kitty graphics APC sequence at the given
// (cols, rows) cell rectangle. The caller is responsible for sizing img to
// (cols*cellPixelW × rows*cellPixelH) — do that via prepareSource. Kitty
// places the image into the cell rectangle preserving source AR, which is
// a no-op when source AR matches cell-rect AR.
func buildKittyAPC(img image.Image, id, cols, rows int) string {
	var buf bytes.Buffer
	encoder := png.Encoder{CompressionLevel: png.BestSpeed}
	if err := encoder.Encode(&buf, img); err != nil {
		return ""
	}
	return buildKittyPNGAPC(buf.Bytes(), id, cols, rows)
}

// kittyPNGOptions builds the transmit options for a PNG image. When tmux
// passthrough is enabled each 4 KiB chunk is wrapped in its own DCS rather
// than wrapping the whole transmission: tmux discards any single DCS larger
// than its input buffer (1 MiB by default), which large images exceed.
func kittyPNGOptions(id, cols, rows int) *kitty.Options {
	o := &kitty.Options{
		Action:           kitty.TransmitAndPut,
		Transmission:     kitty.Direct,
		Format:           kitty.PNG,
		ID:               id,
		Columns:          cols,
		Rows:             rows,
		VirtualPlacement: true,
		Quiet:            2,
		Chunk:            true,
	}
	if tmuxPassthroughEnabled.Load() {
		o.ChunkFormatter = ansi.TmuxPassthrough
	}
	return o
}

// buildKittyPNGAPC is also used by framing regression tests and benchmarks.
func buildKittyPNGAPC(data []byte, id, cols, rows int) string {
	var buf bytes.Buffer
	if err := encodeKittyGraphicsData(&buf, data, kittyPNGOptions(id, cols, rows)); err != nil {
		return ""
	}
	return buf.String()
}

func buildKittyGrid(cols, rows, imageID int) string {
	r := (imageID >> 16) & 0xff
	g := (imageID >> 8) & 0xff
	b := imageID & 0xff
	sgr := fmt.Sprintf("\x1b[38;2;%d;%d;%dm", r, g, b)
	reset := "\x1b[39m"

	var sb strings.Builder
	sb.Grow((cols*4 + len(sgr) + len(reset) + 1) * rows)

	for y := 0; y < rows; y++ {
		sb.WriteString(sgr)
		rowDia := kitty.Diacritic(y)
		for x := 0; x < cols; x++ {
			sb.WriteRune(kitty.Placeholder)
			sb.WriteRune(rowDia)
			sb.WriteRune(kitty.Diacritic(x))
		}
		sb.WriteString(reset)
		if y < rows-1 {
			sb.WriteByte('\n')
		}
	}
	return sb.String()
}

func kittyDeleteImage(id int) string {
	return tmuxWrap(fmt.Sprintf("\x1b_Ga=d,d=I,i=%d,q=2\x1b\\", id))
}
