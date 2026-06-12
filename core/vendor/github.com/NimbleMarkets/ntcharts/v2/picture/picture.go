// Package picture is a source-agnostic image renderer for Bubble Tea.
// It supports half-block glyphs (universal) and the Kitty graphics protocol
// (high-resolution).
// FitMode controls whether images contain, fill, or cover the target cell
// rectangle.
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
	"github.com/NimbleMarkets/pixterm/pkg/ansimage"
	uv "github.com/charmbracelet/ultraviolet"
	"github.com/charmbracelet/x/ansi"
)

// PictureMode selects how images are rendered.
type PictureMode int8

const (
	PictureGlyph PictureMode = iota // Universal half-block ANSI
	PictureKitty                    // High-res Kitty graphics protocol
)

// FitMode controls how the source image is mapped onto the cell rectangle.
// The zero value is FitContain. Out-of-range values are treated as FitContain.
type FitMode int8

const (
	FitContain FitMode = iota // preserve aspect ratio, letterbox (default)
	FitFill                   // stretch to fill the cell rectangle
	FitCover                  // preserve aspect ratio, crop to fill
)

// FitAnchor controls which edge or center is preserved when a fit mode
// must crop overflow. Today only FitCover consults this; FitContain and
// FitFill never crop.
type FitAnchor int8

const (
	AnchorCenter FitAnchor = iota // center crop (default)
	AnchorTop
	AnchorBottom
	AnchorLeft
	AnchorRight
)

const DefaultKittyID = 43

// Sensible defaults for terminal cell pixel size. Most monospace fonts have
// ~1:2 cell ratios (8×16, 9×18, 10×20). Consumers can pre-set via Config or
// update at runtime via Model.SetCellPixelSize when the terminal reports its
// actual cell dims (CSI 16 t).
const (
	defaultCellPixelW = 8
	defaultCellPixelH = 16
)

// Config configures a Model at construction.
type Config struct {
	KittyID    int         // default 43
	Background color.Color // default color.Transparent (no compositing)

	// Fit controls how the source image is mapped onto the cell
	// rectangle. The zero value is FitContain (preserve aspect ratio,
	// letterbox). Use FitFill for games, boards, tile maps, and other
	// coordinate-aligned UIs where source pixels must map exactly to the
	// configured terminal-cell rectangle.
	Fit FitMode

	// Anchor controls which edge or center is preserved when Fit must
	// crop overflow. Only consulted by FitCover today. Zero value is
	// AnchorCenter, matching prior behavior.
	Anchor FitAnchor

	// CellPixelWidth and CellPixelHeight are the terminal cell dimensions in
	// pixels. Used in Kitty mode to pre-scale the source image to the c×r
	// cell rectangle's pixel dimensions before encoding, so Kitty's
	// aspect-ratio-preserving placement fills the cell rectangle. Default
	// 8×16 (typical 1:2 font cell). Update at runtime via
	// Model.SetCellPixelSize when the terminal reports its real cell size.
	CellPixelWidth  int
	CellPixelHeight int

	// KittyResolutionFactor scales the encoded Kitty image's per-cell
	// pixel resolution. Values in (0, 1] shrink the transmitted bitmap;
	// the terminal upscales the image to fill the c×r cell rectangle on
	// display. Default 1.0 (full terminal-pixel resolution). Smaller
	// values produce a chunkier, lower-bandwidth image — useful when
	// the renderer's per-frame composite cost is the bottleneck (e.g.
	// browser-WASM with ghostty-web), or when matching the perceived
	// fidelity of Glyph mode is desirable. Out-of-range values clamp
	// to 1.0.
	KittyResolutionFactor float64
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
	fit        FitMode
	anchor     FitAnchor

	cellPixelW, cellPixelH int

	// kittyResolutionFactor scales the effective per-cell pixel
	// resolution used for Kitty encoding (see Config.KittyResolutionFactor).
	kittyResolutionFactor float64

	// lastRenderedGeom records the (cols, rows, cellPixelW, cellPixelH)
	// of the most recently *applied* KittyFrame — i.e. the geometry
	// currently placed on the terminal. renderCmd compares the current
	// geometry against this snapshot and prepends a kittyDeleteImage to
	// the APC when they differ; some Kitty-protocol terminals (Ghostty,
	// confirmed) don't honor a c/r change for an already-on-screen
	// virtual placement, leaving the previous geometry stuck. Resets to
	// the zero value whenever we explicitly emit kittyDeleteImage
	// (Toggle Kitty→Glyph, SetImage(nil)).
	lastRenderedGeom kittyGeom
}

// kittyGeom is the five-tuple of "what dimensions and fit mode does the Kitty
// image currently on screen occupy". Zero value means "no image currently
// placed at this Model's kittyID" — used as a sentinel by renderCmd to
// skip the delete-prepend on first render.
type kittyGeom struct {
	cols, rows             int
	cellPixelW, cellPixelH int
	fit                    FitMode
	anchor                 FitAnchor
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
	if cfg.CellPixelWidth <= 0 {
		cfg.CellPixelWidth = defaultCellPixelW
	}
	if cfg.CellPixelHeight <= 0 {
		cfg.CellPixelHeight = defaultCellPixelH
	}
	if cfg.KittyResolutionFactor <= 0 || cfg.KittyResolutionFactor > 1 {
		cfg.KittyResolutionFactor = 1.0
	}
	return Model{
		modelID:               nextModelID.Add(1),
		mode:                  PictureGlyph,
		kittyID:               cfg.KittyID,
		background:            cfg.Background,
		cellPixelW:            cfg.CellPixelWidth,
		cellPixelH:            cfg.CellPixelHeight,
		kittyResolutionFactor: cfg.KittyResolutionFactor,
		fit:                   cfg.Fit,
		anchor:                cfg.Anchor,
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
			// Image gone from the terminal: clear the geom snapshot so
			// the next render is treated as a fresh placement (no
			// spurious delete prepended on first re-render).
			m.lastRenderedGeom = kittyGeom{}
			return tea.Raw(kittyDeleteImage(m.kittyID))
		}
		return nil
	}
	return m.renderCmd()
}

// SetSize updates the rendering dimensions in terminal cells. Negative values
// are clamped to 0 — 0 is the existing sentinel for "no size yet" honored by
// renderCmd's <=0 guard, and clamping at the boundary keeps consumers from
// needing to defend against negative-dim arithmetic upstream. Returns a
// render Cmd in Kitty mode (re-encode for the new size) or nil otherwise.
func (m *Model) SetSize(cols, rows int) tea.Cmd {
	if cols < 0 {
		cols = 0
	}
	if rows < 0 {
		rows = 0
	}
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
//
// Caches are NOT eagerly invalidated: the seq bump is enough to invalidate
// them via the cache key check on next render, and keeping the leaving-mode
// cache around lets View show transitional content while the new mode's
// async render is in flight (avoids a visible "blank window" during a
// Glyph→Kitty toggle).
func (m *Model) Toggle() tea.Cmd {
	prev := m.mode
	if m.mode == PictureGlyph {
		// Only enter Kitty when capability is affirmatively Supported.
		// Both Unknown and Unsupported block: Kitty escapes printed to
		// a non-Kitty terminal show up as visible garbage, so we'd
		// rather force a second keypress after the probe resolves than
		// risk a glitch in the early-startup window before the
		// capability lands. Transports where auto-detection is
		// unreliable (ssh multiplexers, tmux passthrough) can opt in
		// via ForceKittyCapability(KittyCapabilitySupported).
		if KittySupported() != KittyCapabilitySupported {
			return nil
		}
		m.mode = PictureKitty
	} else {
		m.mode = PictureGlyph
	}
	m.seq++

	if prev == PictureKitty && m.img != nil {
		// Leaving Kitty: the Kitty image is being deleted from the
		// terminal registry; the placeholder grid would resolve to
		// nothing now, so clear it. Also clear the geom snapshot —
		// nothing is placed at this kittyID anymore.
		m.invalidateKitty()
		m.lastRenderedGeom = kittyGeom{}
		return tea.Raw(kittyDeleteImage(m.kittyID))
	}
	return m.renderCmd()
}

// Mode returns the current rendering mode.
func (m *Model) Mode() PictureMode { return m.mode }

// Fit returns the current fit mode.
func (m *Model) Fit() FitMode { return m.fit }

// Anchor returns the current fit anchor.
func (m *Model) Anchor() FitAnchor { return m.anchor }

// SetFit updates the fit mode. No-ops if fit is unchanged. Otherwise stores
// it, bumps seq, invalidates both render caches, and returns m.renderCmd()
// (nil in Glyph mode, a render Cmd in Kitty mode with an image set).
func (m *Model) SetFit(fit FitMode) tea.Cmd {
	if fit == m.fit {
		return nil
	}
	m.fit = fit
	m.seq++
	m.invalidateGlyph()
	m.invalidateKitty()
	return m.renderCmd()
}

// SetAnchor updates the fit anchor. No-ops if anchor is unchanged. Otherwise
// stores it, bumps seq, invalidates both render caches, and returns
// m.renderCmd() (nil in Glyph mode, a render Cmd in Kitty mode with an image
// set).
func (m *Model) SetAnchor(anchor FitAnchor) tea.Cmd {
	if anchor == m.anchor {
		return nil
	}
	m.anchor = anchor
	m.seq++
	m.invalidateGlyph()
	m.invalidateKitty()
	return m.renderCmd()
}

// Init returns a Cmd that asks the terminal for its cell pixel size and
// probes Kitty graphics support. The cell-size response auto-applies via
// SetCellPixelSize; the Kitty probe response auto-applies to the
// process-wide capability state read by KittySupported. Consumers
// batch this with their own Init Cmd.
func (m *Model) Init() tea.Cmd {
	return tea.Batch(RequestCellSize(), QueryKittySupport())
}

// KittySupported is a convenience for KittySupported() — the Kitty
// graphics capability is process-wide, not per-Model.
func (m *Model) KittySupported() KittyCapability { return KittySupported() }

// CellPixelSize returns the configured terminal cell pixel size used to
// pre-scale Kitty image sources to the placement cell rectangle.
func (m *Model) CellPixelSize() (w, h int) {
	return m.cellPixelW, m.cellPixelH
}

// SetCellPixelSize updates the terminal cell pixel size used for Kitty
// placements. Non-positive values are clamped to 1. Returns a render Cmd if
// the new size differs from the current one and there's an in-flight image
// in Kitty mode; otherwise nil.
func (m *Model) SetCellPixelSize(w, h int) tea.Cmd {
	if w < 1 {
		w = 1
	}
	if h < 1 {
		h = 1
	}
	if w == m.cellPixelW && h == m.cellPixelH {
		return nil
	}
	m.cellPixelW = w
	m.cellPixelH = h
	m.seq++
	m.invalidateKitty()
	return m.renderCmd()
}

// KittyResolutionFactor returns the current Kitty-image resolution
// multiplier. See Config.KittyResolutionFactor.
func (m *Model) KittyResolutionFactor() float64 { return m.kittyResolutionFactor }

// SetKittyResolutionFactor updates the multiplier applied to cell pixel
// dimensions when encoding Kitty images. Values in (0, 1] shrink the
// transmitted bitmap; the terminal upscales to fill the cell rectangle.
// Out-of-range values clamp to 1.0. Returns a render Cmd if the factor
// changed and a Kitty image is currently placed; otherwise nil.
func (m *Model) SetKittyResolutionFactor(f float64) tea.Cmd {
	if f <= 0 || f > 1 {
		f = 1.0
	}
	if f == m.kittyResolutionFactor {
		return nil
	}
	m.kittyResolutionFactor = f
	m.seq++
	m.invalidateKitty()
	return m.renderCmd()
}

// String returns the rendered image content as a plain string.
func (m *Model) String() string { return m.View().Content }

// applyKittyGridMsg is the second half of the KittyFrameMsg pipeline.
// KittyFrameMsg's handler returns a tea.Sequence that first emits the APC via
// tea.Raw and then sends this msg, so the new image is placed at kittyID
// before View starts rendering placeholder cells that reference it. Setting
// kittyGrid synchronously in the KittyFrameMsg handler caused the next render
// to emit cells pointing at a kittyID still holding the *previous* image,
// producing a one-frame "previous-image" flash during navigation.
type applyKittyGridMsg struct {
	modelID uint64
	// Grid is a pure function of (cols, rows, kittyID); seq is NOT used
	// for staleness because SetImage bumps seq without invalidating the
	// grid. We compare geometry instead — if any of these changed since
	// the grid was computed, the grid is stale and gets dropped. This
	// matters in WASM where Kitty encode time can exceed the tick
	// interval, so multiple SetImage bumps happen between KittyFrameMsg
	// and applyKittyGridMsg arrival.
	cols, rows, kittyID int
	grid                string
}

// IsPictureMsg reports whether msg is a picture-related async update that
// should be forwarded to picture models. These messages are shared at the
// Bubble Tea program/process level, not necessarily owned by a single
// picture.Model; individual Model.Update calls filter by model ID where
// applicable.
//
// Includes uv.CellSizeEvent and uv.KittyGraphicsEvent because Update
// auto-applies them — consumers that gate forwarding on this helper must route
// the terminal's CSI 16 t reply AND Kitty query reply to Update, or Kitty
// placements stay at the default 8×16 cell-pixel size and the Kitty capability
// stays Unknown.
func IsPictureMsg(msg tea.Msg) bool {
	switch msg.(type) {
	case KittyFrameMsg, applyKittyGridMsg, uv.CellSizeEvent, uv.KittyGraphicsEvent, kittyProbeTickMsg:
		return true
	}
	return false
}

// Update processes the picture component's own messages. Forward every tea.Msg
// to it; unknown messages are ignored and return nil. A uv.CellSizeEvent
// (the terminal's reply to RequestCellSize) is auto-applied via
// SetCellPixelSize so consumers don't need to relay it manually.
func (m *Model) Update(msg tea.Msg) tea.Cmd {
	switch msg := msg.(type) {
	case KittyFrameMsg:
		if msg.modelID != m.modelID || msg.Seq != m.seq {
			return nil
		}
		// Record the geometry now: lastRenderedGeom is consumed by the
		// next renderCmd, and any SetSize that arrives between the APC
		// emission and the deferred grid apply must see this snapshot
		// to compute delete-prev correctly.
		m.lastRenderedGeom = kittyGeom{
			cols:       m.cols,
			rows:       m.rows,
			cellPixelW: m.cellPixelW,
			cellPixelH: m.cellPixelH,
			fit:        m.fit,
			anchor:     m.anchor,
		}
		modelID, grid := m.modelID, msg.Grid
		gridCols, gridRows, gridID := m.cols, m.rows, m.kittyID
		return tea.Sequence(
			tea.Raw(msg.APC),
			func() tea.Msg {
				return applyKittyGridMsg{modelID: modelID, cols: gridCols, rows: gridRows, kittyID: gridID, grid: grid}
			},
		)
	case applyKittyGridMsg:
		if msg.modelID != m.modelID {
			return nil
		}
		// Geometry-based staleness: SetImage bumps seq but doesn't change
		// (cols, rows, kittyID), so an in-flight grid stays valid across
		// SetImage. SetSize / kittyID changes do invalidate.
		if msg.cols != m.cols || msg.rows != m.rows || msg.kittyID != m.kittyID {
			return nil
		}
		m.kittyGrid = msg.grid
		return nil
	case uv.CellSizeEvent:
		return m.SetCellPixelSize(msg.Width, msg.Height)
	case uv.KittyGraphicsEvent:
		recordKittyResponse(msg)
		return nil
	case kittyProbeTickMsg:
		recordKittyTimeout()
		return nil
	}
	return nil
}

// RequestCellSize returns a Cmd that asks the terminal for its cell pixel
// dimensions via CSI 16 t (XTWINOPS). The terminal replies with a
// uv.CellSizeEvent which Model.Update auto-applies via SetCellPixelSize, so
// consumers typically just batch this with their own Init Cmd and forward
// every tea.Msg to Model.Update as usual.
func RequestCellSize() tea.Cmd {
	return tea.Raw(ansi.WindowOp(16))
}

// View returns the rendered image as a tea.View, or an empty view if there is
// no image or no size. In Kitty mode the placeholder grid is returned; if it
// hasn't been computed yet (e.g. during a Glyph→Kitty toggle while the new
// frame is being encoded), View falls through to render Glyph half-blocks of
// the current image as a transitional fallback, so consumers don't see a
// blank window during the mode switch.
//
// The Model never renders user-facing loading or error text; layers above
// (e.g. pictureurl) own that.
func (m *Model) View() tea.View {
	if m.img == nil || m.cols <= 0 || m.rows <= 0 {
		return tea.NewView("")
	}

	if m.mode == PictureKitty && m.kittyGrid != "" {
		return tea.NewView(m.kittyGrid)
	}
	// Falls through here in two cases:
	//   - mode == PictureGlyph (the normal Glyph path)
	//   - mode == PictureKitty but kittyGrid hasn't been computed yet
	//     (transitional fallback during a Glyph→Kitty toggle)

	key := fmt.Sprintf("%d|%d|%d|%d|%d", m.seq, m.cols, m.rows, m.fit, m.anchor)
	if m.glyphKey == key && m.glyphCache != "" {
		return tea.NewView(m.glyphCache)
	}

	rendered := prepareSource(m.img, m.fit, m.cols, m.rows, m.cellPixelW, m.cellPixelH, m.background, m.anchor)
	if rendered == nil {
		return tea.NewView("")
	}
	// ScaleModeResize (not Fit): prepareSource already applied the chosen
	// FitMode against the actual cell pixel dimensions, producing a bitmap
	// whose AR matches the cell rect. ansimage's job here is "render into
	// the half-block grid at exactly (cols, rows*2)", not "preserve AR
	// again" — pixterm hardcodes a 1:2 cell assumption that disagrees
	// with the prepared bitmap on terminals reporting non-1:2 cell ratios
	// (line-spacing, retina cells), causing Glyph to letterbox while Kitty
	// fills. Resize keeps the two backends consistent.
	ascii, err := ansimage.NewScaledFromImage(
		rendered,
		m.rows*2,
		m.cols,
		m.background,
		ansimage.ScaleModeResize,
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
	// Capture inputs by value; defer the heavy work (prepareSource's
	// CatmullRom scale + bg compositing, plus buildKittyAPC's PNG encode)
	// to the returned closure so SetImage/SetSize/SetFit/SetAnchor/Update return
	// immediately and bubbletea runs the render off the main loop.
	img, bg := m.img, m.background
	modelID, id, cols, rows, seq := m.modelID, m.kittyID, m.cols, m.rows, m.seq
	fit := m.fit
	anchor := m.anchor
	// Apply kittyResolutionFactor to the cell-pixel dims used for the
	// transmitted image. The placement rectangle (cols × rows cells) is
	// unchanged, so the terminal upscales the smaller source image to
	// fill the cell area on display.
	cpw := int(float64(m.cellPixelW) * m.kittyResolutionFactor)
	cph := int(float64(m.cellPixelH) * m.kittyResolutionFactor)
	if cpw < 1 {
		cpw = 1
	}
	if cph < 1 {
		cph = 1
	}
	prevGeom := m.lastRenderedGeom
	return func() tea.Msg {
		prepared := prepareSource(img, fit, cols, rows, cpw, cph, bg, anchor)
		if prepared == nil {
			return nil
		}
		// prepareSource just ran a CatmullRom 4-tap scale over the full
		// cell-rect; give JS a slice before the PNG encode (no-op on
		// native). Without this, WASM holds the thread for the entire
		// scale+encode duration and queued fetch resolves / key events
		// can't drain.
		yieldToJS()
		apc := buildKittyAPC(prepared, id, cols, rows)
		yieldToJS()
		currGeom := kittyGeom{cols: cols, rows: rows, cellPixelW: cpw, cellPixelH: cph, fit: fit, anchor: anchor}
		if prevGeom != (kittyGeom{}) && prevGeom != currGeom {
			apc = kittyDeleteImage(id) + apc
		}
		grid := buildKittyGrid(cols, rows, id)
		return KittyFrameMsg{modelID: modelID, ID: id, Seq: seq, APC: apc, Grid: grid}
	}
}
