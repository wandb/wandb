// Package picture is a source-agnostic image renderer for Bubble Tea.
// It supports half-block glyphs (universal) and the Kitty graphics protocol
// (high-resolution).
//
// Use picture/pictureurl for URL-driven fetching on top of this base.

package picture

import (
	"fmt"
	"image"
	"image/color"
	_ "image/gif"  // decoder registration
	_ "image/jpeg" // decoder registration
	_ "image/png"  // decoder registration
	"strings"
	"sync/atomic"

	tea "charm.land/bubbletea/v2"
	"github.com/eliukblau/pixterm/pkg/ansimage"
)

// PictureMode selects how images are rendered.
type PictureMode int8

const (
	PictureGlyph PictureMode = iota // Universal half-block ANSI
	PictureKitty                    // High-res Kitty graphics protocol
)

const DefaultKittyID = 43

// Config configures a Model at construction.
type Config struct {
	KittyID    int         // default 43
	Background color.Color // default color.Transparent (no compositing)
}

// Model renders an image.Image as half-blocks or Kitty graphics inside a
// Bubble Tea program. The Model has no notion of where images come from;
// callers feed it via SetImage. For URL-driven fetching, see pictureurl.
type Model struct {
	modelID    uint64
	mode       PictureMode
	cols, rows int

	img image.Image
	seq uint64

	glyphCache string
	glyphKey   string

	kittyGrid string

	kittyID    int
	background color.Color
}

var nextModelID atomic.Uint64

// New returns a Model with default Config.
func New() Model {
	return NewWithConfig(Config{})
}

// NewWithConfig returns a Model with the supplied Config. Zero/nil fields
// are filled with defaults.
func NewWithConfig(cfg Config) Model {
	if cfg.KittyID <= 0 {
		cfg.KittyID = DefaultKittyID
	}
	if cfg.Background == nil {
		cfg.Background = color.Transparent
	}
	return Model{
		modelID:    nextModelID.Add(1),
		mode:       PictureGlyph,
		kittyID:    cfg.KittyID,
		background: cfg.Background,
	}
}

// SetImage sets the image to render. Pass nil to clear. Returns a tea.Cmd if
// rendering needs to be scheduled (Kitty mode), or a cleanup Cmd if Kitty was
// previously placed and is now being cleared, or nil otherwise.
//
// In Kitty mode with a non-nil new image, the previous placeholder grid is
// preserved until the new KittyFrameMsg arrives. The grid is a pure function
// of (cols, rows, kittyID) — byte-identical between renders when those are
// stable — and the previously-resident image at kittyID stays visible until
// the new APC overwrites it. Clearing the grid synchronously would create a
// visible blank window during animation.
func (m *Model) SetImage(img image.Image) tea.Cmd {
	prev := m.img
	m.img = img
	m.seq++
	m.invalidateGlyph()

	if img == nil {
		m.invalidateKitty()
		if m.mode == PictureKitty && prev != nil {
			return tea.Raw(kittyDeleteImage(m.kittyID))
		}
		return nil
	}
	return m.renderCmd()
}

// SetSize updates the rendering dimensions in terminal cells. Returns a render
// Cmd in Kitty mode (re-encode for the new size) or nil otherwise.
func (m *Model) SetSize(cols, rows int) tea.Cmd {
	if cols == m.cols && rows == m.rows {
		return nil
	}
	m.cols = cols
	m.rows = rows
	m.seq++
	m.invalidateGlyph()
	m.invalidateKitty()
	return m.renderCmd()
}

// Toggle switches between Glyph and Kitty modes. When toggling away from
// Kitty after an image was placed, returns a Cmd that emits the Kitty delete
// sequence; otherwise returns the Cmd to render in the new mode (or nil).
func (m *Model) Toggle() tea.Cmd {
	prev := m.mode
	if m.mode == PictureGlyph {
		m.mode = PictureKitty
	} else {
		m.mode = PictureGlyph
	}
	m.seq++
	m.invalidateGlyph()
	m.invalidateKitty()

	if prev == PictureKitty && m.img != nil {
		return tea.Raw(kittyDeleteImage(m.kittyID))
	}
	return m.renderCmd()
}

// Mode returns the current rendering mode.
func (m *Model) Mode() PictureMode { return m.mode }

// String returns the rendered image content as a plain string.
func (m *Model) String() string { return m.View().Content }

// IsPictureMsg reports whether msg is a picture-owned async update.
func IsPictureMsg(msg tea.Msg) bool {
	switch msg.(type) {
	case KittyFrameMsg:
		return true
	}
	return false
}

// Update processes the picture component's own messages. Forward every tea.Msg
// to it; unknown messages are ignored and return nil.
func (m *Model) Update(msg tea.Msg) tea.Cmd {
	switch msg := msg.(type) {
	case KittyFrameMsg:
		if msg.modelID != m.modelID || msg.Seq != m.seq {
			return nil
		}
		m.kittyGrid = msg.Grid
		return tea.Raw(msg.APC)
	}
	return nil
}

// View returns the rendered image as a tea.View, or an empty view if there is
// no image, no size, or (in Kitty mode) the encoded frame is not yet ready.
// The Model never renders user-facing loading or error text; layers above
// (e.g. pictureurl) own that.
func (m *Model) View() tea.View {
	if m.img == nil || m.cols <= 0 || m.rows <= 0 {
		return tea.NewView("")
	}

	if m.mode == PictureKitty {
		return tea.NewView(m.kittyGrid)
	}

	key := fmt.Sprintf("%d|%d|%d", m.seq, m.cols, m.rows)
	if m.glyphKey == key && m.glyphCache != "" {
		return tea.NewView(m.glyphCache)
	}

	rendered := composite(m.img, m.background)
	ascii, err := ansimage.NewScaledFromImage(
		rendered,
		m.rows*2,
		m.cols,
		m.background,
		ansimage.ScaleModeFit,
		ansimage.NoDithering,
	)
	if err != nil {
		return tea.NewView("")
	}

	// pixterm/ansimage appends \n after every row including the last; the
	// Kitty path does not. Strip so both modes report the same shape to
	// newline-aware layout code (lipgloss.JoinVertical, etc.).
	out := strings.TrimRight(ascii.RenderExt(false, false), "\n")
	m.glyphCache = out
	m.glyphKey = key
	return tea.NewView(out)
}

func (m *Model) invalidateGlyph() {
	m.glyphCache = ""
	m.glyphKey = ""
}

func (m *Model) invalidateKitty() {
	m.kittyGrid = ""
}

func (m *Model) renderCmd() tea.Cmd {
	if m.mode != PictureKitty || m.img == nil || m.cols <= 0 || m.rows <= 0 {
		return nil
	}
	img := composite(m.img, m.background)
	modelID, id, cols, rows, seq := m.modelID, m.kittyID, m.cols, m.rows, m.seq
	return func() tea.Msg {
		apc := buildKittyAPC(img, id, cols, rows)
		grid := buildKittyGrid(cols, rows, id)
		return KittyFrameMsg{modelID: modelID, ID: id, Seq: seq, APC: apc, Grid: grid}
	}
}
