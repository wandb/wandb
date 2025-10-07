// ntcharts - Copyright (c) 2024 Neomantra Corp.

package canvas

// File contains methods and objects used during canvas Model Update()
// to modify internal state.
// canvas is able to move the viewport displaying the contents
// either up, down, left and right

import (
	"github.com/charmbracelet/bubbles/key"
	tea "github.com/charmbracelet/bubbletea"
)

type KeyMap struct {
	Up     key.Binding
	Down   key.Binding
	Left   key.Binding
	Right  key.Binding
	PgUp   key.Binding
	PgDown key.Binding
}

// DefaultKeyMap returns a default KeyMap for canvas.
func DefaultKeyMap() KeyMap {
	return KeyMap{
		Up: key.NewBinding(
			key.WithKeys("up", "k"),
			key.WithHelp("↑/k", "move up"),
		),
		Down: key.NewBinding(
			key.WithKeys("down", "j"),
			key.WithHelp("↓/j", "move down"),
		),
		Left: key.NewBinding(
			key.WithKeys("left", "h"),
			key.WithHelp("←/h", "move left"),
		),
		Right: key.NewBinding(
			key.WithKeys("right", "l"),
			key.WithHelp("→/l", "move right"),
		),
		PgUp: key.NewBinding(
			key.WithKeys("pgup"),
			key.WithHelp("PgUp", "zoom in"),
		),
		PgDown: key.NewBinding(
			key.WithKeys("pgdown"),
			key.WithHelp("PgDown", "zoom out"),
		),
	}
}

// UpdateHandler callback invoked during an Update()
// and passes in the canvas *Model and bubbletea Msg.
type UpdateHandler func(*Model, tea.Msg)

// DefaultUpdateHandler is used by canvas chart to enable
// moving viewing window using the mouse wheel,
// holding down mouse left button and moving,
// and with the arrow keys.
// Uses canvas Keymap for keyboard messages.
func DefaultUpdateHandler() UpdateHandler {
	var lastPos Point // tracks zone position of last zone mouse position
	return func(m *Model, tm tea.Msg) {
		switch msg := tm.(type) {
		case tea.KeyMsg:
			switch {
			case key.Matches(msg, m.KeyMap.Up):
				m.MoveUp(1)
			case key.Matches(msg, m.KeyMap.Down):
				m.MoveDown(1)
			case key.Matches(msg, m.KeyMap.Left):
				m.MoveLeft(1)
			case key.Matches(msg, m.KeyMap.Right):
				m.MoveRight(1)
			case key.Matches(msg, m.KeyMap.PgUp):
				m.MoveUp(1)
			case key.Matches(msg, m.KeyMap.PgDown):
				m.MoveDown(1)
			}
		case tea.MouseMsg:
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				m.MoveUp(1)
			case tea.MouseButtonWheelDown:
				m.MoveDown(1)
			case tea.MouseButtonWheelRight:
				m.MoveRight(1)
			case tea.MouseButtonWheelLeft:
				m.MoveLeft(1)
			}

			if m.zoneManager == nil {
				return
			}
			switch msg.Action {
			case tea.MouseActionPress:
				zInfo := m.zoneManager.Get(m.zoneID)
				if zInfo.InBounds(msg) {
					x, y := zInfo.Pos(msg)
					lastPos = Point{X: x, Y: y} // set position of last click
				}
			case tea.MouseActionMotion: // event occurs when mouse is pressed
				zInfo := m.zoneManager.Get(m.zoneID)
				if zInfo.InBounds(msg) {
					x, y := zInfo.Pos(msg)
					if x > lastPos.X {
						m.MoveRight(1)
					} else if x < lastPos.X {
						m.MoveLeft(1)
					}
					if y > lastPos.Y {
						m.MoveDown(1)
					} else if y < lastPos.Y {
						m.MoveUp(1)
					}
					lastPos = Point{X: x, Y: y} // update last mouse position
				}
			}
		}
	}
}

// MoveUp moves cursor up if possible.
func (m *Model) MoveUp(i int) {
	m.cursor.Y -= i
	if m.cursor.Y < 0 {
		m.cursor.Y = 0
	}
}

// MoveDown moves cursor down if possible.
func (m *Model) MoveDown(i int) {
	endY := m.cursor.Y + m.ViewHeight + i
	if endY <= m.area.Dy() {
		m.cursor.Y += i
	}
}

// MoveLeft moves cursor left if possible.
func (m *Model) MoveLeft(i int) {
	m.cursor.X -= i
	if m.cursor.X < 0 {
		m.cursor.X = 0
	}
}

// MoveRight moves cursor right if possible.
func (m *Model) MoveRight(i int) {
	endX := m.cursor.X + m.ViewWidth + 1
	if endX <= m.area.Dx() {
		m.cursor.X += i
	}
}
