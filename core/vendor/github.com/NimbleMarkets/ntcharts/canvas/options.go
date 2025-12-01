// ntcharts - Copyright (c) 2024 Neomantra Corp.

package canvas

// File contains options used by the canvas during initialization with New().

import (
	"github.com/charmbracelet/lipgloss"
	zone "github.com/lrstanley/bubblezone"
)

// Option is used to set options when initializing a sparkline. Example:
//
//	canvas := New(width, height, WithStyle(someStyle), WithKeyMap(someKeyMap))
type Option func(*Model)

// WithStyle sets the default Cell style.
func WithStyle(s lipgloss.Style) Option {
	return func(m *Model) {
		m.Style = s
	}
}

// WithKeyMap sets the KeyMap used
// when processing keyboard event messages in Update().
func WithKeyMap(k KeyMap) Option {
	return func(m *Model) {
		m.KeyMap = k
	}
}

// WithUpdateHandler sets the UpdateHandler used
// when processing bubbletea Msg events in Update().
func WithUpdateHandler(h UpdateHandler) Option {
	return func(m *Model) {
		m.UpdateHandler = h
	}
}

// WithZoneManager sets the bubblezone Manager used
// when processing bubbletea Msg mouse events in Update().
func WithZoneManager(zm *zone.Manager) Option {
	return func(m *Model) {
		m.SetZoneManager(zm)
	}
}

// WithCursor sets the cursor starting position for the viewport.
func WithCursor(p Point) Option {
	return func(m *Model) {
		m.SetCursor(p)
	}
}

// WithFocus sets the canvas to be focused.
func WithFocus() Option {
	return func(m *Model) {
		m.Focus()
	}
}

// WithContent copies the given []string into
// the contents of the canvas with default style.
// Each string will be copied into a row starting
// from the top of the canvas to bottom.
// Use option WithStyle() to set canvas style
// before using WithContent() for styling.
func WithContent(l []string) Option {
	return func(m *Model) {
		m.SetLines(l)
	}
}

// WithViewWidth sets the viewport width of the canvas.
func WithViewWidth(w int) Option {
	return func(m *Model) {
		m.ViewWidth = w
	}
}

// WithViewHeight sets the viewport height of the canvas.
func WithViewHeight(h int) Option {
	return func(m *Model) {
		m.ViewHeight = h
	}
}
