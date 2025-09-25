// ntcharts - Copyright (c) 2024 Neomantra Corp.

package timeserieslinechart

// File contains methods and objects used during
// timeserieslinechart Model Update() to modify internal state.
// timeserieslinechart is able to zoom in and out of the graph,
// and increase and decrease the X values to simulating moving
// the viewport of the linechart

import (
	"github.com/NimbleMarkets/ntcharts/linechart"
)

// DateUpdateHandler is used by timeserieslinechart to enable
// zooming in and out with the mouse wheel or page up and page down,
// moving the viewing window by holding down mouse button and moving,
// and moving the viewing window with the arrow keys.
// There is only movement along the X axis by day increments.
// Uses linechart Canvas Keymap for keyboard messages.
func DateUpdateHandler(i int) linechart.UpdateHandler {
	daySeconds := 86400 * i // number of seconds in a day
	return linechart.XAxisUpdateHandler(float64(daySeconds))
}

// DateNoZoomUpdateHandler is used by timeserieslinechart to enable
// moving the viewing window by using the mouse scroll wheel,
// holding down mouse button and moving,
// and moving the viewing window with the arrow keys.
// There is only movement along the X axis by day increments.
// Uses linechart Canvas Keymap for keyboard messages.
func DateNoZoomUpdateHandler(i int) linechart.UpdateHandler {
	daySeconds := 86400 * i // number of seconds in a day
	return linechart.XAxisNoZoomUpdateHandler(float64(daySeconds))
}

// HourUpdateHandler is used by timeserieslinechart to enable
// zooming in and out with the mouse wheel or page up and page down,
// moving the viewing window by holding down mouse button and moving,
// and moving the viewing window with the arrow keys.
// There is only movement along the X axis by hour increments.
// Uses linechart Canvas Keymap for keyboard messages.
func HourUpdateHandler(i int) linechart.UpdateHandler {
	hourSeconds := 3600 * i // number of seconds in a hour
	return linechart.XAxisUpdateHandler(float64(hourSeconds))
}

// HourNoZoomUpdateHandler is used by timeserieslinechart to enable
// moving the viewing window by using the mouse scroll wheel,
// holding down mouse button and moving,
// and moving the viewing window with the arrow keys.
// There is only movement along the X axis by hour increments.
// Uses linechart Canvas Keymap for keyboard messages.
func HourNoZoomUpdateHandler(i int) linechart.UpdateHandler {
	hourSeconds := 3600 * i // number of seconds in a hour
	return linechart.XAxisNoZoomUpdateHandler(float64(hourSeconds))
}

// SecondUpdateHandler is used by timeserieslinechart to enable
// zooming in and out with the mouse wheel or page up and page down,
// moving the viewing window by holding down mouse button and moving,
// and moving the viewing window with the arrow keys.
// There is only movement along the X axis by second increments.
// Uses linechart Canvas Keymap for keyboard messages.
func SecondUpdateHandler(i int) linechart.UpdateHandler {
	return linechart.XAxisUpdateHandler(float64(i))
}

// SecondNoZoomUpdateHandler is used by timeserieslinechart to enable
// moving the viewing window by using the mouse scroll wheel,
// holding down mouse button and moving,
// and moving the viewing window with the arrow keys.
// There is only movement along the X axis by second increments.
// Uses linechart Canvas Keymap for keyboard messages.
func SecondNoZoomUpdateHandler(i int) linechart.UpdateHandler {
	return linechart.XAxisNoZoomUpdateHandler(float64(i))
}
