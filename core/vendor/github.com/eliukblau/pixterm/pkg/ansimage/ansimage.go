//       ___  _____  ____
//      / _ \/  _/ |/_/ /____ ______ _
//     / ___// /_>  </ __/ -_) __/  ' \
//    /_/  /___/_/|_|\__/\__/_/ /_/_/_/
//
//    Copyright 2017 Eliuk Blau
//
//    This Source Code Form is subject to the terms of the Mozilla Public
//    License, v. 2.0. If a copy of the MPL was not distributed with this
//    file, You can obtain one at https://mozilla.org/MPL/2.0/.

package ansimage

import (
	"errors"
	"fmt"

	"io"
	"net/http"
	"os"
	"strings"

	"image"
	"image/color"
	"image/draw"

	_ "image/gif"  // initialize decoder
	_ "image/jpeg" // initialize decoder
	_ "image/png"  // initialize decoder

	_ "golang.org/x/image/bmp"  // initialize decoder
	_ "golang.org/x/image/tiff" // initialize decoder
	_ "golang.org/x/image/webp" // initialize decoder

	"github.com/disintegration/imaging"
	"github.com/lucasb-eyer/go-colorful"
)

// Unicode Block Element character used to represent lower pixel in terminal row.
// INFO: https://en.wikipedia.org/wiki/Block_Elements
const lowerHalfBlock = "\u2584"

// Unicode Block Element characters used to represent dithering in terminal row.
// INFO: https://en.wikipedia.org/wiki/Block_Elements
const fullBlock = "\u2588"
const darkShadeBlock = "\u2593"
const mediumShadeBlock = "\u2592"
const lightShadeBlock = "\u2591"

// ANSImage scale modes:
// resize (full scaled to area),
// fill (resize and crop the image with a center anchor point to fill area),
// fit (resize the image to fit area, preserving the aspect ratio).
const (
	ScaleModeResize = ScaleMode(iota)
	ScaleModeFill
	ScaleModeFit
)

// ANSImage dithering modes:
// no dithering (classic mode: half block based),
// chars (use characters to represent brightness),
// blocks (use character blocks to represent brightness).
const (
	NoDithering = DitheringMode(iota)
	DitheringWithBlocks
	DitheringWithChars
)

// ANSImage block size in pixels (dithering mode)
const (
	BlockSizeY = 8
	BlockSizeX = 4
)

var (
	// ErrImageDownloadFailed occurs in the attempt to download an image and the status code of the response is not "200 OK".
	ErrImageDownloadFailed = errors.New("ANSImage: image download failed")

	// ErrHeightNonMoT occurs when ANSImage height is not a Multiple of Two value.
	ErrHeightNonMoT = errors.New("ANSImage: height must be a Multiple of Two value")

	// ErrInvalidBoundsMoT occurs when ANSImage height or width are invalid values (Multiple of Two).
	ErrInvalidBoundsMoT = errors.New("ANSImage: height or width must be >=2")

	// ErrOutOfBounds occurs when ANSI-pixel coordinates are out of ANSImage bounds.
	ErrOutOfBounds = errors.New("ANSImage: out of bounds")

	// errUnknownScaleMode occurs when scale mode is invalid.
	errUnknownScaleMode = errors.New("ANSImage: unknown scale mode")

	// errUnknownDitheringMode occurs when dithering mode is invalid.
	errUnknownDitheringMode = errors.New("ANSImage: unknown dithering mode")
)

// ScaleMode type is used for image scale mode constants.
type ScaleMode uint8

// DitheringMode type is used for image scale dithering mode constants.
type DitheringMode uint8

// ANSIpixel represents a pixel of an ANSImage.
type ANSIpixel struct {
	Brightness uint8
	R, G, B    uint8
	upper      bool
	source     *ANSImage
}

// ANSImage represents an image encoded in ANSI escape codes.
type ANSImage struct {
	h, w      int
	maxprocs  int
	bgR       uint8
	bgG       uint8
	bgB       uint8
	dithering DitheringMode
	pixmap    [][]*ANSIpixel
}

// Render returns the ANSI-compatible string form of ANSI-pixel.
func (ap *ANSIpixel) Render() string {
	return ap.RenderExt(false, false)
}

// RenderExt returns the ANSI-compatible string form of ANSI-pixel.
// Can specify if it renders in form of Go code 'fmt.Printf()'.
// Can specify if background color will be disabled in dithering mode.
func (ap *ANSIpixel) RenderExt(renderGoCode, disableBgColor bool) string {
	backslash033 := "\033"
	if renderGoCode {
		backslash033 = "\\033"
	}

	// WITHOUT DITHERING
	if ap.source.dithering == NoDithering {
		var renderStr string
		if ap.upper {
			renderStr = fmt.Sprintf(
				"%s[48;2;%d;%d;%dm",
				backslash033,
				ap.R, ap.G, ap.B,
			)
		} else {
			renderStr = fmt.Sprintf(
				"%s[38;2;%d;%d;%dm%s",
				backslash033,
				ap.R, ap.G, ap.B,
				lowerHalfBlock,
			)
		}
		return renderStr
	}

	// WITH DITHERING
	block := " "
	if ap.source.dithering == DitheringWithBlocks {
		switch bri := ap.Brightness; {
		case bri > 204:
			block = fullBlock
		case bri > 152:
			block = darkShadeBlock
		case bri > 100:
			block = mediumShadeBlock
		case bri > 48:
			block = lightShadeBlock
		}
	} else if ap.source.dithering == DitheringWithChars {
		switch bri := ap.Brightness; {
		case bri > 230:
			block = "#"
		case bri > 207:
			block = "&"
		case bri > 184:
			block = "$"
		case bri > 161:
			block = "X"
		case bri > 138:
			block = "x"
		case bri > 115:
			block = "="
		case bri > 92:
			block = "+"
		case bri > 69:
			block = ";"
		case bri > 46:
			block = ":"
		case bri > 23:
			block = "."
		}
	} else {
		panic(errUnknownDitheringMode)
	}

	bgColorStr := fmt.Sprintf(
		"%s[48;2;%d;%d;%dm",
		backslash033,
		ap.source.bgR, ap.source.bgG, ap.source.bgB,
	)
	if disableBgColor {
		bgColorStr = ""
	}
	return fmt.Sprintf(
		"%s%s[38;2;%d;%d;%dm%s",
		bgColorStr,
		backslash033,
		ap.R, ap.G, ap.B,
		block,
	)
}

// Height gets total rows of ANSImage.
func (ai *ANSImage) Height() int {
	return ai.h
}

// Width gets total columns of ANSImage.
func (ai *ANSImage) Width() int {
	return ai.w
}

// DitheringMode gets the dithering mode of ANSImage.
func (ai *ANSImage) DitheringMode() DitheringMode {
	return ai.dithering
}

// SetMaxProcs sets the maximum number of parallel goroutines to render the ANSImage
// (user should manually sets `runtime.GOMAXPROCS(max)` before to this change takes effect).
func (ai *ANSImage) SetMaxProcs(max int) {
	ai.maxprocs = max
}

// GetMaxProcs gets the maximum number of parallels goroutines to render the ANSImage.
func (ai *ANSImage) GetMaxProcs() int {
	return ai.maxprocs
}

// SetAt sets ANSI-pixel color (RBG) and brightness in coordinates (y,x).
func (ai *ANSImage) SetAt(y, x int, r, g, b, brightness uint8) error {
	if y >= 0 && y < ai.h && x >= 0 && x < ai.w {
		ai.pixmap[y][x].R = r
		ai.pixmap[y][x].G = g
		ai.pixmap[y][x].B = b
		ai.pixmap[y][x].Brightness = brightness
		ai.pixmap[y][x].upper = ((ai.dithering == NoDithering) && (y%2 == 0))
		return nil
	}
	return ErrOutOfBounds
}

// GetAt gets ANSI-pixel in coordinates (y,x).
func (ai *ANSImage) GetAt(y, x int) (*ANSIpixel, error) {
	if y >= 0 && y < ai.h && x >= 0 && x < ai.w {
		return &ANSIpixel{
				R:          ai.pixmap[y][x].R,
				G:          ai.pixmap[y][x].G,
				B:          ai.pixmap[y][x].B,
				Brightness: ai.pixmap[y][x].Brightness,
				upper:      ai.pixmap[y][x].upper,
				source:     ai.pixmap[y][x].source,
			},
			nil
	}
	return nil, ErrOutOfBounds
}

// Render returns the ANSI-compatible string form of ANSImage.
func (ai *ANSImage) Render() string {
	return ai.RenderExt(false, false)
}

// RenderExt returns the ANSI-compatible string form of ANSImage.
// Can specify if it renders in form of Go code 'fmt.Printf()'.
// Can specify if background color will be disabled in dithering mode.
// (Nice info for ANSI True Colour - https://gist.github.com/XVilka/8346728)
func (ai *ANSImage) RenderExt(renderGoCode, disableBgColor bool) string {
	type renderData struct {
		row    int
		render string
	}

	backslashN := "\n"
	backslash033 := "\033"
	if renderGoCode {
		backslashN = "\\n"
		backslash033 = "\\033"
	}

	// WITHOUT DITHERING
	if ai.dithering == NoDithering {
		rows := make([]string, ai.h/2)
		for y := 0; y < ai.h; y += ai.maxprocs {
			ch := make(chan renderData, ai.maxprocs)
			for n, r := 0, y+1; (n <= ai.maxprocs) && (2*r+1 < ai.h); n, r = n+1, y+n+1 {
				go func(r, y int) {
					var str string
					for x := 0; x < ai.w; x++ {
						str += ai.pixmap[y][x].RenderExt(renderGoCode, disableBgColor)   // upper pixel
						str += ai.pixmap[y+1][x].RenderExt(renderGoCode, disableBgColor) // lower pixel
					}
					str += fmt.Sprintf("%s[0m%s", backslash033, backslashN) // reset ansi style
					ch <- renderData{row: r, render: str}
				}(r, 2*r)
				// DEBUG:
				// fmt.Printf("y:%d | n:%d | r:%d | 2*r:%d\n", y, n, r, 2*r)
				// time.Sleep(time.Millisecond * 100)
			}
			for n, r := 0, y+1; (n <= ai.maxprocs) && (2*r+1 < ai.h); n, r = n+1, y+n+1 {
				data := <-ch
				if renderGoCode {
					data.render = fmt.Sprintf(`fmt.Print("%s")%s`, data.render, "\n")
				}
				rows[data.row] = data.render
				// DEBUG:
				// fmt.Printf("data.row:%d\n", data.row)
				// time.Sleep(time.Millisecond * 100)
			}
		}
		return strings.Join(rows, "")
	}

	// WITH DITHERING
	rows := make([]string, ai.h)
	for y := 0; y < ai.h; y += ai.maxprocs {
		ch := make(chan renderData, ai.maxprocs)
		for n, r := 0, y; (n <= ai.maxprocs) && (r+1 < ai.h); n, r = n+1, y+n+1 {
			go func(y int) {
				var str string
				for x := 0; x < ai.w; x++ {
					str += ai.pixmap[y][x].RenderExt(renderGoCode, disableBgColor)
				}
				str += fmt.Sprintf("%s[0m%s", backslash033, backslashN) // reset ansi style
				ch <- renderData{row: y, render: str}
			}(r)
		}
		for n, r := 0, y; (n <= ai.maxprocs) && (r+1 < ai.h); n, r = n+1, y+n+1 {
			data := <-ch
			if renderGoCode {
				data.render = fmt.Sprintf(`fmt.Print("%s")%s`, data.render, "\n")
			}
			rows[data.row] = data.render
		}
	}
	return strings.Join(rows, "")
}

// Draw writes the ANSImage to standard output (terminal).
func (ai *ANSImage) Draw() {
	ai.DrawExt(false, false)
}

// DrawExt writes the ANSImage to standard output (terminal).
// Can specify if it prints in form of Go code 'fmt.Printf()'.
// Can specify if background color will be disabled in dithering mode.
func (ai *ANSImage) DrawExt(renderGoCode, disableBgColor bool) {
	fmt.Print(ai.RenderExt(renderGoCode, disableBgColor))
}

// New creates a new empty ANSImage ready to draw on it.
func New(h, w int, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	if (dm == NoDithering) && (h%2 != 0) {
		return nil, ErrHeightNonMoT
	}

	if h < 2 || w < 2 {
		return nil, ErrInvalidBoundsMoT
	}

	r, g, b, _ := bg.RGBA()
	ansimage := &ANSImage{
		h: h, w: w,
		maxprocs:  1,
		bgR:       uint8(r),
		bgG:       uint8(g),
		bgB:       uint8(b),
		dithering: dm,
		pixmap:    nil,
	}

	ansimage.pixmap = func() [][]*ANSIpixel {
		v := make([][]*ANSIpixel, h)
		for y := 0; y < h; y++ {
			v[y] = make([]*ANSIpixel, w)
			for x := 0; x < w; x++ {
				v[y][x] = &ANSIpixel{
					R:          0,
					G:          0,
					B:          0,
					Brightness: 0,
					source:     ansimage,
					upper:      ((dm == NoDithering) && (y%2 == 0)),
				}
			}
		}
		return v
	}()

	return ansimage, nil
}

// NewFromImage creates a new ANSImage from an image.Image.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewFromImage(image image.Image, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	return createANSImage(image, bg, dm)
}

// NewScaledFromImage creates a new scaled ANSImage from an image.Image.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewScaledFromImage(image image.Image, y, x int, bg color.Color, sm ScaleMode, dm DitheringMode) (*ANSImage, error) {
	switch sm {
	case ScaleModeResize:
		image = imaging.Resize(image, x, y, imaging.Lanczos)
	case ScaleModeFill:
		image = imaging.Fill(image, x, y, imaging.Center, imaging.Lanczos)
	case ScaleModeFit:
		image = imaging.Fit(image, x, y, imaging.Lanczos)
	default:
		panic(errUnknownScaleMode)
	}

	return createANSImage(image, bg, dm)
}

// NewFromReader creates a new ANSImage from an io.Reader.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewFromReader(reader io.Reader, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	image, _, err := image.Decode(reader)
	if err != nil {
		return nil, err
	}

	return createANSImage(image, bg, dm)
}

// NewScaledFromReader creates a new scaled ANSImage from an io.Reader.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewScaledFromReader(reader io.Reader, y, x int, bg color.Color, sm ScaleMode, dm DitheringMode) (*ANSImage, error) {
	image, _, err := image.Decode(reader)
	if err != nil {
		return nil, err
	}

	switch sm {
	case ScaleModeResize:
		image = imaging.Resize(image, x, y, imaging.Lanczos)
	case ScaleModeFill:
		image = imaging.Fill(image, x, y, imaging.Center, imaging.Lanczos)
	case ScaleModeFit:
		image = imaging.Fit(image, x, y, imaging.Lanczos)
	default:
		panic(errUnknownScaleMode)
	}

	return createANSImage(image, bg, dm)
}

// NewFromFile creates a new ANSImage from a file.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewFromFile(name string, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	reader, err := os.Open(name)
	if err != nil {
		return nil, err
	}
	defer reader.Close()
	return NewFromReader(reader, bg, dm)
}

// NewScaledFromFile creates a new scaled ANSImage from a file.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewScaledFromFile(name string, y, x int, bg color.Color, sm ScaleMode, dm DitheringMode) (*ANSImage, error) {
	reader, err := os.Open(name)
	if err != nil {
		return nil, err
	}
	defer reader.Close()
	return NewScaledFromReader(reader, y, x, bg, sm, dm)
}

// NewFromURL creates a new ANSImage from an image URL.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewFromURL(url string, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	res, err := http.Get(url)
	if err != nil {
		return nil, err
	}
	if res.StatusCode != http.StatusOK {
		return nil, ErrImageDownloadFailed
	}
	defer res.Body.Close()
	return NewFromReader(res.Body, bg, dm)
}

// NewScaledFromURL creates a new scaled ANSImage from an image URL.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewScaledFromURL(url string, y, x int, bg color.Color, sm ScaleMode, dm DitheringMode) (*ANSImage, error) {
	res, err := http.Get(url)
	if err != nil {
		return nil, err
	}
	if res.StatusCode != http.StatusOK {
		return nil, ErrImageDownloadFailed
	}
	defer res.Body.Close()
	return NewScaledFromReader(res.Body, y, x, bg, sm, dm)
}

// ClearTerminal clears current terminal buffer using ANSI escape code.
// (Nice info for ANSI escape codes - https://unix.stackexchange.com/questions/124762/how-does-clear-command-work)
func ClearTerminal() {
	fmt.Print("\033[H\033[2J")
}

// createANSImage loads data from an image and returns an ANSImage.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func createANSImage(img image.Image, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	var rgbaOut *image.RGBA
	bounds := img.Bounds()

	// do compositing only if background color has no transparency (thank you @disq for the idea!)
	// (info - https://stackoverflow.com/questions/36595687/transparent-pixel-color-go-lang-image)
	if _, _, _, a := bg.RGBA(); a >= 0xffff {
		rgbaOut = image.NewRGBA(bounds)
		draw.Draw(rgbaOut, bounds, image.NewUniform(bg), image.Point{}, draw.Src)
		draw.Draw(rgbaOut, bounds, img, image.Point{}, draw.Over)
	} else {
		if v, ok := img.(*image.RGBA); ok {
			rgbaOut = v
		} else {
			rgbaOut = image.NewRGBA(bounds)
			draw.Draw(rgbaOut, bounds, img, image.Point{}, draw.Src)
		}
	}

	yMin, xMin := bounds.Min.Y, bounds.Min.X
	yMax, xMax := bounds.Max.Y, bounds.Max.X

	if dm == NoDithering {
		// always sets an even number of ANSIPixel rows...
		yMax = yMax - yMax%2 // one for upper pixel and another for lower pixel --> without dithering
	} else {
		yMax = yMax / BlockSizeY // always sets 1 ANSIPixel block...
		xMax = xMax / BlockSizeX // per 8x4 real pixels --> with dithering
	}

	ansimage, err := New(yMax, xMax, bg, dm)
	if err != nil {
		return nil, err
	}

	if dm == NoDithering {
		for y := yMin; y < yMax; y++ {
			for x := xMin; x < xMax; x++ {
				v := rgbaOut.RGBAAt(x, y)
				if err := ansimage.SetAt(y, x, v.R, v.G, v.B, 0); err != nil {
					return nil, err
				}
			}
		}
	} else {
		pixelCount := BlockSizeY * BlockSizeX

		for y := yMin; y < yMax; y++ {
			for x := xMin; x < xMax; x++ {

				var sumR, sumG, sumB, sumBri float64
				for dy := 0; dy < BlockSizeY; dy++ {
					py := BlockSizeY*y + dy

					for dx := 0; dx < BlockSizeX; dx++ {
						px := BlockSizeX*x + dx

						pixel := rgbaOut.At(px, py)
						color, _ := colorful.MakeColor(pixel)
						_, _, v := color.Hsv()
						sumR += color.R
						sumG += color.G
						sumB += color.B
						sumBri += v
					}
				}

				r := uint8(sumR/float64(pixelCount)*255.0 + 0.5)
				g := uint8(sumG/float64(pixelCount)*255.0 + 0.5)
				b := uint8(sumB/float64(pixelCount)*255.0 + 0.5)
				brightness := uint8(sumBri/float64(pixelCount)*255.0 + 0.5)

				if err := ansimage.SetAt(y, x, r, g, b, brightness); err != nil {
					return nil, err
				}
			}
		}
	}

	return ansimage, nil
}
