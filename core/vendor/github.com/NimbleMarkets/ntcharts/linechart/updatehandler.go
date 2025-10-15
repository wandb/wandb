// ntcharts - Copyright (c) 2024 Neomantra Corp.

package linechart

// File contains methods and objects used during linechart Model Update()
// to modify internal state.
// linechart is able to zoom in and out of the graph,
// and increase and decrease the X and Y values to simulating moving
// the viewport of the linechart

import (
	"github.com/NimbleMarkets/ntcharts/canvas"

	"github.com/charmbracelet/bubbles/key"
	tea "github.com/charmbracelet/bubbletea"
)

// UpdateHandler callback invoked during an Update()
// and passes in the linechart Model and bubbletea Msg.
type UpdateHandler func(*Model, tea.Msg)

// XYAxesUpdateHandler is used by linechart to enable
// zooming in and out with the mouse wheel or page up and page down,
// moving the viewing window by holding down mouse button and moving,
// and moving the viewing window with the arrow keys.
// Uses linechart Canvas Keymap for keyboard messages.
func XYAxesUpdateHandler(xIncrement, yIncrement float64) UpdateHandler {
	var lastPos canvas.Point
	return func(m *Model, tm tea.Msg) {
		switch msg := tm.(type) {
		case tea.KeyMsg:
			keyXYHandler(m, msg, xIncrement, yIncrement)
			keyXYZoomHandler(m, msg, xIncrement, yIncrement)
		case tea.MouseMsg:
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				// zoom in limited values cannot cross
				m.ZoomIn(xIncrement, yIncrement)
			case tea.MouseButtonWheelDown:
				// zoom out limited by max values
				m.ZoomOut(xIncrement, yIncrement)
			}
			mouseActionXYHandler(m, msg, &lastPos, xIncrement, yIncrement)
		}
	}
}

// XAxisUpdateHandler is used by linechart to enable
// zooming in and out with the mouse wheel or page up and page down,
// moving the viewing window by holding down mouse button and moving,
// and moving the viewing window with the arrow keys.
// There is only movement along the X axis with the given increment.
// Uses linechart Canvas Keymap for keyboard messages.
func XAxisUpdateHandler(increment float64) UpdateHandler {
	var lastPos canvas.Point
	return func(m *Model, tm tea.Msg) {
		switch msg := tm.(type) {
		case tea.KeyMsg:
			keyXHandler(m, msg, increment)
			keyXZoomHandler(m, msg, increment)
		case tea.MouseMsg:
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				// zoom in limited values cannot cross
				m.ZoomIn(increment, 0)
			case tea.MouseButtonWheelDown:
				// zoom out limited by max values
				m.ZoomOut(increment, 0)
			}
			mouseActionXHandler(m, msg, &lastPos, increment)
		}
	}
}

// XAxisNoZoomUpdateHandler is used by linechart to enable
// moving the viewing window along the X axis with mouse wheel,
// holding down the mouse button and moving, and with arrow keys.
// There is only movement along the X axis with the given increment.
// Uses linechart Canvas Keymap for keyboard messages.
func XAxisNoZoomUpdateHandler(increment float64) UpdateHandler {
	var lastPos canvas.Point
	return func(m *Model, tm tea.Msg) {
		switch msg := tm.(type) {
		case tea.KeyMsg:
			keyXHandler(m, msg, increment)
		case tea.MouseMsg:
			switch msg.Button {
			case tea.MouseButtonWheelUp, tea.MouseButtonWheelLeft:
				m.MoveLeft(increment)
			case tea.MouseButtonWheelDown, tea.MouseButtonWheelRight:
				m.MoveRight(increment)
			}
			mouseActionXHandler(m, msg, &lastPos, increment)
		}
	}
}

// YAxisUpdateHandler is used by steamlinechart to enable
// zooming in and out with the mouse wheel or page up and page down,
// moving the viewing window by holding down mouse button and moving,
// and moving the viewing window with the arrow keys.
// There is only movement along the Y axis with the given increment.
// Uses linechart Canvas Keymap for keyboard messages.
func YAxisUpdateHandler(increment float64) UpdateHandler {
	var lastPos canvas.Point
	return func(m *Model, tm tea.Msg) {
		switch msg := tm.(type) {
		case tea.KeyMsg:
			keyYHandler(m, msg, increment)
			keyYZoomHandler(m, msg, increment)
		case tea.MouseMsg:
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				// zoom in limited values cannot cross
				m.ZoomIn(0, increment)
			case tea.MouseButtonWheelDown:
				// zoom out limited by max values
				m.ZoomOut(0, increment)
			}
			mouseActionYHandler(m, msg, &lastPos, increment)
		}
	}
}

// YAxisNoZoomUpdateHandler is used by steamlinechart to enable
// moving the viewing window along the Y axis with mouse wheel,
// holding down the mouse button and moving, and with arrow keys.
// There is only movement along the Y axis with the given increment.
// Uses linechart Canvas Keymap for keyboard messages.
func YAxisNoZoomUpdateHandler(increment float64) UpdateHandler {
	var lastPos canvas.Point
	return func(m *Model, tm tea.Msg) {
		switch msg := tm.(type) {
		case tea.KeyMsg:
			keyYHandler(m, msg, increment)
		case tea.MouseMsg:
			switch msg.Button {
			case tea.MouseButtonWheelUp:
				m.MoveUp(increment)
			case tea.MouseButtonWheelDown:
				m.MoveDown(increment)
			}
			mouseActionYHandler(m, msg, &lastPos, increment)
		}
	}
}

// ZoomIn will update display X and Y values to simulate
// zooming into the linechart by given increments.
func (m *Model) ZoomIn(x, y float64) {
	m.SetViewXYRange(
		m.viewMinX+x,
		m.viewMaxX-x,
		m.viewMinY+y,
		m.viewMaxY-y,
	)
}

// ZoomOut will update display X and Y values to simulate
// zooming into the linechart by given increments.
func (m *Model) ZoomOut(x, y float64) {
	m.SetViewXYRange(
		m.viewMinX-x,
		m.viewMaxX+x,
		m.viewMinY-y,
		m.viewMaxY+y,
	)
}

// MoveLeft will update display Y values to simulate
// moving left on the linechart by given increment
func (m *Model) MoveLeft(i float64) {
	if (m.viewMinX - i) >= m.MinX() {
		m.SetViewXRange(m.viewMinX-i, m.viewMaxX-i)
	} else {
		i = m.viewMinX - m.MinX()
		m.SetViewXRange(m.viewMinX-i, m.viewMaxX-i)
	}
}

// MoveRight will update display Y values to simulate
// moving right on the linechart by given increment.
func (m *Model) MoveRight(i float64) {
	if (m.viewMaxX + i) <= m.MaxX() {
		m.SetViewXRange(m.viewMinX+i, m.viewMaxX+i)
	} else {
		i = m.MaxX() - m.viewMaxX
		m.SetViewXRange(m.viewMinX+i, m.viewMaxX+i)
	}
}

// MoveUp will update display X values to simulate
// moving up on the linechart chart by given increment.
func (m *Model) MoveUp(i float64) {
	if (m.viewMaxY + i) <= m.MaxY() {
		m.SetViewYRange(m.viewMinY+i, m.viewMaxY+i)
	} else {
		i = m.MaxY() - m.viewMaxY
		m.SetViewYRange(m.viewMinY+i, m.viewMaxY+i)
	}
}

// MoveDown will update display Y values to simulate
// moving down on the linechart chart by given increment.
func (m *Model) MoveDown(i float64) {
	if (m.viewMinY - i) >= m.MinY() {
		m.SetViewYRange(m.viewMinY-i, m.viewMaxY-i)
	} else {
		i = m.viewMinY - m.MinY()
		m.SetViewYRange(m.viewMinY-i, m.viewMaxY-i)
	}

}

// keyXYHandler handles keyboard messages for X and Y axis moving
func keyXYHandler(m *Model, msg tea.KeyMsg, xIncrement, yIncrement float64) {
	switch {
	case key.Matches(msg, m.Canvas.KeyMap.Up):
		m.MoveUp(yIncrement)
	case key.Matches(msg, m.Canvas.KeyMap.Down):
		m.MoveDown(yIncrement)
	case key.Matches(msg, m.Canvas.KeyMap.Left):
		m.MoveLeft(xIncrement)
	case key.Matches(msg, m.Canvas.KeyMap.Right):
		m.MoveRight(xIncrement)
	}
}

// keyXHandler handles keyboard messages for X axis moving
func keyXHandler(m *Model, msg tea.KeyMsg, xIncrement float64) {
	switch {
	case key.Matches(msg, m.Canvas.KeyMap.Left):
		m.MoveLeft(xIncrement)
	case key.Matches(msg, m.Canvas.KeyMap.Right):
		m.MoveRight(xIncrement)
	}
}

// keyYHandler handles keyboard messages for Y axis moving
func keyYHandler(m *Model, msg tea.KeyMsg, yIncrement float64) {
	switch {
	case key.Matches(msg, m.Canvas.KeyMap.Up):
		m.MoveUp(yIncrement)
	case key.Matches(msg, m.Canvas.KeyMap.Down):
		m.MoveDown(yIncrement)
	}
}

// keyXYZoomHandler handles keyboard messages for X and Y axis zooming
func keyXYZoomHandler(m *Model, msg tea.KeyMsg, xIncrement, yIncrement float64) {
	switch {
	case key.Matches(msg, m.Canvas.KeyMap.PgUp):
		m.ZoomIn(xIncrement, yIncrement)
	case key.Matches(msg, m.Canvas.KeyMap.PgDown):
		m.ZoomOut(xIncrement, yIncrement)
	}
}

// keyXZoomHandler handles keyboard messages for X axis zooming
func keyXZoomHandler(m *Model, msg tea.KeyMsg, xIncrement float64) {
	switch {
	case key.Matches(msg, m.Canvas.KeyMap.PgUp):
		m.ZoomIn(xIncrement, 0)
	case key.Matches(msg, m.Canvas.KeyMap.PgDown):
		m.ZoomOut(xIncrement, 0)
	}
}

// keyYZoomHandler handles keyboard messages for Y axis zooming
func keyYZoomHandler(m *Model, msg tea.KeyMsg, yIncrement float64) {
	switch {
	case key.Matches(msg, m.Canvas.KeyMap.PgUp):
		m.ZoomIn(0, yIncrement)
	case key.Matches(msg, m.Canvas.KeyMap.PgDown):
		m.ZoomOut(0, yIncrement)
	}
}

// mouseActionXYHandler handles mouse click messages for X and Y axes
func mouseActionXYHandler(m *Model, msg tea.MouseMsg, lastPos *canvas.Point, xIncrement, yIncrement float64) {
	if m.ZoneManager() == nil {
		return
	}
	switch msg.Action {
	case tea.MouseActionPress:
		zInfo := m.ZoneManager().Get(m.ZoneID())
		if zInfo.InBounds(msg) {
			x, y := zInfo.Pos(msg)
			*lastPos = canvas.Point{X: x, Y: y}
		}
	case tea.MouseActionMotion:
		zInfo := m.ZoneManager().Get(m.ZoneID())
		if zInfo.InBounds(msg) {
			x, y := zInfo.Pos(msg)
			if x > lastPos.X {
				m.MoveRight(xIncrement)
			} else if x < lastPos.X {
				m.MoveLeft(xIncrement)
			}
			if y > lastPos.Y {
				m.MoveDown(yIncrement)
			} else if y < lastPos.Y {
				m.MoveUp(yIncrement)
			}
			*lastPos = canvas.Point{X: x, Y: y}
		}
	}
}

// mouseActionXHandler handles mouse click messages for X axis
func mouseActionXHandler(m *Model, msg tea.MouseMsg, lastPos *canvas.Point, increment float64) {
	if m.ZoneManager() == nil {
		return
	}
	switch msg.Action {
	case tea.MouseActionPress:
		zInfo := m.ZoneManager().Get(m.ZoneID())
		if zInfo.InBounds(msg) {
			x, y := zInfo.Pos(msg)
			*lastPos = canvas.Point{X: x, Y: y}
		}
	case tea.MouseActionMotion:
		zInfo := m.ZoneManager().Get(m.ZoneID())
		if zInfo.InBounds(msg) {
			x, y := zInfo.Pos(msg)
			if x > lastPos.X {
				m.MoveRight(increment)
			} else if x < lastPos.X {
				m.MoveLeft(increment)
			}
			*lastPos = canvas.Point{X: x, Y: y}
		}
	}

}

// mouseActionYHandler handles mouse click messages for Y axis
func mouseActionYHandler(m *Model, msg tea.MouseMsg, lastPos *canvas.Point, increment float64) {
	if m.ZoneManager() == nil {
		return
	}
	switch msg.Action {
	case tea.MouseActionPress:
		zInfo := m.ZoneManager().Get(m.ZoneID())
		if zInfo.InBounds(msg) {
			x, y := zInfo.Pos(msg)
			*lastPos = canvas.Point{X: x, Y: y} // set position of last click
		}
	case tea.MouseActionMotion: // event occurs when mouse is pressed
		zInfo := m.ZoneManager().Get(m.ZoneID())
		if zInfo.InBounds(msg) {
			x, y := zInfo.Pos(msg)
			if y > lastPos.Y {
				m.MoveDown(increment)
			} else if y < lastPos.Y {
				m.MoveUp(increment)
			}
			*lastPos = canvas.Point{X: x, Y: y} // update last mouse position
		}
	}
}
