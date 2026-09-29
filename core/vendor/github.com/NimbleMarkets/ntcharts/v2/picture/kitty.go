package picture

import (
	"bytes"
	"fmt"
	"image"
	"image/color"
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
func buildKittyAPC(img image.Image, id, cols, rows int, format KittyFormat, z ...int) string {
	if format == KittyFormatRGBA {
		b := img.Bounds()
		data := kittyRGBABytes(img)
		if data == nil {
			return ""
		}
		return buildKittyRGBAAPC(data, b.Dx(), b.Dy(), id, cols, rows, z...)
	}
	var buf bytes.Buffer
	encoder := png.Encoder{CompressionLevel: png.BestSpeed}
	if err := encoder.Encode(&buf, img); err != nil {
		return ""
	}
	return buildKittyPNGAPC(buf.Bytes(), id, cols, rows, z...)
}

// KittyFormat selects how a Kitty frame's pixels are transmitted.
type KittyFormat int8

const (
	// KittyFormatPNG encodes each frame as a BestSpeed PNG (f=100). Small
	// on the wire; costs an encode per frame, which dominates on WASM.
	KittyFormatPNG KittyFormat = iota
	// KittyFormatRGBA sends raw straight-alpha RGBA bytes (f=32). No
	// encode, no decode in the terminal, but 4 bytes per pixel before
	// base64 — about 5.3 bytes per pixel through the terminal stream.
	KittyFormatRGBA
)

func (f KittyFormat) String() string {
	if f == KittyFormatRGBA {
		return "rgba"
	}
	return "png"
}

func normalizeKittyFormat(f KittyFormat) KittyFormat {
	if f != KittyFormatRGBA {
		return KittyFormatPNG
	}
	return f
}

func kittyRGBAOptions(width, height, id, cols, rows int, z ...int) *kitty.Options {
	o := kittyPNGOptions(id, cols, rows, z...)
	o.Format = kitty.RGBA
	o.ImageWidth = width
	o.ImageHeight = height
	return o
}

func buildKittyRGBAAPC(data []byte, width, height, id, cols, rows int, z ...int) string {
	var buf bytes.Buffer
	if err := encodeKittyGraphicsData(&buf, data, kittyRGBAOptions(width, height, id, cols, rows, z...)); err != nil {
		return ""
	}
	return buf.String()
}

// kittyRGBABytes returns img as tightly packed straight-alpha RGBA rows.
func kittyRGBABytes(img image.Image) []byte {
	b := img.Bounds()
	if b.Empty() {
		return nil
	}
	out := make([]byte, 4*b.Dx()*b.Dy())
	writeKittyRGBA(out, img)
	return out
}

// writeKittyRGBA fills a caller-owned buffer of 4*width*height bytes. Shared
// memory uses this directly, avoiding an intermediate full-frame allocation.
// NRGBA rows are copied; RGBA pixels are un-premultiplied where translucent.
func writeKittyRGBA(out []byte, img image.Image) {
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	rowBytes := 4 * w
	switch src := img.(type) {
	case *image.NRGBA:
		for y := range h {
			copy(out[y*rowBytes:(y+1)*rowBytes], src.Pix[y*src.Stride:y*src.Stride+rowBytes])
		}
	case *image.RGBA:
		for y := range h {
			row := src.Pix[y*src.Stride : y*src.Stride+rowBytes]
			dst := out[y*rowBytes : (y+1)*rowBytes]
			for x := 0; x < rowBytes; x += 4 {
				switch a := row[x+3]; a {
				case 255:
					copy(dst[x:x+4], row[x:x+4])
				case 0:
					clear(dst[x : x+4])
				default:
					// Same 16-bit un-premultiply and rounding as
					// color.NRGBAModel, inlined so no colour values
					// are boxed per pixel.
					a16 := uint32(a) * 0x101
					dst[x] = byte((uint32(row[x]) * 0x101 * 0xffff / a16) >> 8)
					dst[x+1] = byte((uint32(row[x+1]) * 0x101 * 0xffff / a16) >> 8)
					dst[x+2] = byte((uint32(row[x+2]) * 0x101 * 0xffff / a16) >> 8)
					dst[x+3] = a
				}
			}
		}
	default:
		at := 0
		for y := b.Min.Y; y < b.Max.Y; y++ {
			for x := b.Min.X; x < b.Max.X; x++ {
				c := color.NRGBAModel.Convert(img.At(x, y)).(color.NRGBA)
				out[at], out[at+1], out[at+2], out[at+3] = c.R, c.G, c.B, c.A
				at += 4
			}
		}
	}
}

// kittyPNGOptions wraps each chunk separately for tmux, including RGBA
// and shared-memory payloads that reuse these options.
func kittyPNGOptions(id, cols, rows int, z ...int) *kitty.Options {
	depth := 0
	if len(z) > 0 {
		depth = z[0]
	}
	o := &kitty.Options{Z: depth,
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
func buildKittyPNGAPC(data []byte, id, cols, rows int, z ...int) string {
	var buf bytes.Buffer
	if err := encodeKittyGraphicsData(&buf, data, kittyPNGOptions(id, cols, rows, z...)); err != nil {
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
