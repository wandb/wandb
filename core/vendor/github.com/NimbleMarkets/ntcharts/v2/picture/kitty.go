package picture

import (
	"bytes"
	"fmt"
	"image"
	"strings"

	"github.com/charmbracelet/x/ansi/kitty"
)

// buildKittyAPC encodes img as a Kitty graphics APC sequence at the given
// (cols, rows) cell rectangle. The caller is responsible for sizing img to
// (cols*cellPixelW × rows*cellPixelH) — do that via prepareSource. Kitty
// places the image into the cell rectangle preserving source AR, which is
// a no-op when source AR matches cell-rect AR.
func buildKittyAPC(img image.Image, id, cols, rows int) string {
	var buf bytes.Buffer
	opts := &kitty.Options{
		Action:           kitty.TransmitAndPut,
		Transmission:     kitty.Direct,
		Format:           kitty.PNG,
		ID:               id,
		Columns:          cols,
		Rows:             rows,
		VirtualPlacement: true,
		Quite:            2,
		Chunk:            true,
	}
	if err := kitty.EncodeGraphics(&buf, img, opts); err != nil {
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
	return fmt.Sprintf("\x1b_Ga=d,d=I,i=%d,q=2\x1b\\", id)
}
