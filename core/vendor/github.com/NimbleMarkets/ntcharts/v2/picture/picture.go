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
		mode:       PictureGlyph,
		kittyID:    cfg.KittyID,
		background: cfg.Background,
	}
}

// SetImage sets the image to render. Pass nil to clear. Returns a tea.Cmd if
// rendering needs to be scheduled (Kitty mode), or a cleanup Cmd if Kitty was
// previously placed and is now being cleared, or nil otherwise.
func (m *Model) SetImage(img image.Image) tea.Cmd {
	prev := m.img
	m.img = img
	m.seq++
	m.invalidate()

	if img == nil {
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
	m.invalidate()
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
	m.invalidate()

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
		if msg.ID != m.kittyID || msg.Seq != m.seq {
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

	out := ascii.RenderExt(false, false)
	m.glyphCache = out
	m.glyphKey = key
	return tea.NewView(out)
}

func (m *Model) invalidate() {
	m.glyphCache = ""
	m.glyphKey = ""
	m.kittyGrid = ""
}

func (m *Model) renderCmd() tea.Cmd {
	if m.mode != PictureKitty || m.img == nil || m.cols <= 0 || m.rows <= 0 {
		return nil
	}
	img := composite(m.img, m.background)
	id, cols, rows, seq := m.kittyID, m.cols, m.rows, m.seq
	return func() tea.Msg {
		apc := buildKittyAPC(img, id, cols, rows)
		grid := buildKittyGrid(cols, rows, id)
		return KittyFrameMsg{ID: id, Seq: seq, APC: apc, Grid: grid}
	}
}
