// liveindicator.go
//
// Run state indicators. A live run's mark in the workspace runs list
// breathes — its color fades to the terminal background ("not filled") and
// back to the run color. The status bar's leftmost cell shows the state of
// the current run: an empty circle until the state is known, then a filled
// dot in the state color, blinking while the run is live.
package leet

import (
	"image/color"
	"math"
	"time"

	"charm.land/lipgloss/v2"
)

const (
	// liveDotMark is the filled-circle glyph for known run states.
	liveDotMark = "●"

	// idleDotMark is the empty-circle glyph shown before a run's state
	// is known.
	idleDotMark = "○"

	// livePulsePeriod is the duration of one full breathing cycle.
	livePulsePeriod = 1500 * time.Millisecond

	// LivePulseFrame is the redraw interval while a breathing indicator is
	// on screen. The phase is derived from the wall clock, so all live
	// indicators breathe in sync regardless of which view drives redraws.
	LivePulseFrame = 125 * time.Millisecond
)

// livePulseAlpha returns the breathing phase in [0, 1] at now:
// 0 at full color, 1 at the fully faded-out point of the cycle.
func livePulseAlpha(now time.Time) float64 {
	period := livePulsePeriod.Milliseconds()
	phase := float64(now.UnixMilli()%period) / float64(period)
	return 0.5 - 0.5*math.Cos(2*math.Pi*phase)
}

// runMarkPulseColor returns the color of a live run's list mark at now:
// the run color breathing all the way down to the terminal background and
// back, so the mark empties out and refills once per cycle.
func runMarkPulseColor(runColor AdaptiveColor, now time.Time) color.Color {
	r, g, b := rgb8(runColor)
	tr, tg, tb := terminalBackgroundRGB()
	return blendRGB(r, g, b, tr, tg, tb, livePulseAlpha(now))
}

// The status bar's background (colorLayoutHighlight) is light in both color
// schemes, so its state dot always uses the dark color variants.
var (
	statusBarFinishedColor = colorRunning.Light
	statusBarCrashedColor  = colorCrashed.Light
)

// statusBarPulseColor returns the status bar's blinking live dot color at
// now: the running green fading into the bar's own background and back.
func statusBarPulseColor(now time.Time) color.Color {
	r, g, b := rgb8(statusBarFinishedColor)
	tr, tg, tb := rgb8(colorLayoutHighlight)
	return blendRGB(r, g, b, tr, tg, tb, livePulseAlpha(now))
}

// renderStateIndicator renders a status bar's leftmost cell for a run in
// the given state. Shared by the single-run view (its run) and the
// workspace (the run under the cursor).
func renderStateIndicator(state RunState) string {
	glyph := idleDotMark
	fg := moon900

	switch state {
	case RunStateRunning:
		glyph = liveDotMark
		fg = statusBarPulseColor(time.Now())
	case RunStateFinished:
		glyph = liveDotMark
		fg = statusBarFinishedColor
	case RunStateCrashed, RunStateFailed:
		glyph = liveDotMark
		fg = statusBarCrashedColor
	}

	return lipgloss.NewStyle().
		Foreground(fg).
		Background(colorLayoutHighlight).
		Padding(0, 0, 0, StatusBarPadding).
		Render(glyph)
}

// rgb8 extracts 8-bit RGB components from a color.
func rgb8(c color.Color) (r, g, b uint8) {
	r16, g16, b16, _ := c.RGBA()
	return uint8(r16 >> 8), uint8(g16 >> 8), uint8(b16 >> 8)
}
