// ntcharts - Copyright (c) 2026 Neomantra Corp.

package linechart

// File contains the tick generator for log axes. Linear axes label every
// xStep / yStep cells and do not use it.

import (
	"math"
	"strconv"
)

// tick is one axis label: a value, the row or column it falls on (counted
// from the axis origin), and its formatted text.
type tick struct {
	pos   int
	value float64
	label string
}

// logAxis describes a log axis to label: the displayed range min..max
// (sanitized, min < max), laid out over size cells with labels allowed on
// positions 0..last and at least step cells apart.
type logAxis struct {
	min, max   float64
	size, last int
	step       int
	format     LabelFormatter
	// labelCells reports whether labels run along the axis (X) and so take
	// len(label) cells plus a gap, rather than one row each (Y).
	labelCells bool
}

// endSlack is how far, in cells, a tick may be from an end of the axis and
// still be labelled on the end cell. The end cells read as the range's
// minimum and maximum, so a value that merely rounds onto one is left out.
const endSlack = 0.25

// tick returns the label for value v on the cell it falls on. ok is false
// if that would put it on an end cell without being at that end.
func (a logAxis) tick(v float64) (t tick, ok bool) {
	exact := ScaleLog.span(a.min, v) / ScaleLog.span(a.min, a.max) * float64(a.size)
	p := max(0, min(int(math.Round(exact)), a.last))
	if (p == 0 && exact > endSlack) || (p == a.last && exact < float64(a.size)-endSlack) {
		return tick{}, false
	}
	t = tick{pos: p, value: v, label: a.format(p, v)}
	// A label that would run off the end of the axis is never drawn where
	// it falls. On the last cell it is kept for the caller's final-label
	// rule (see overflows); elsewhere it is left out.
	if a.overflows(t) && p != a.last {
		return tick{}, false
	}
	return t, true
}

// overflows reports whether a label running along the axis would be cut
// off at the far end if drawn from its own cell.
func (a logAxis) overflows(t tick) bool {
	return a.labelCells && t.pos+len(t.label) > a.size+1
}

// clear reports whether tick hi can be drawn after tick lo.
func (a logAxis) clear(lo, hi tick) bool {
	gap := max(a.step, 1)
	if a.labelCells {
		gap = max(gap, len(lo.label)+1)
	}
	return hi.pos-lo.pos >= gap
}

// logValue returns digit * 10^exp, exactly as its decimal literal parses.
func logValue(digit, exp int) float64 {
	v, _ := strconv.ParseFloat(strconv.Itoa(digit)+"e"+strconv.Itoa(exp), 64)
	return v
}

// inRange reports whether v lies in the axis range, allowing for drift at
// the bounds.
func (a logAxis) inRange(v float64) bool {
	p := math.Log10(v)
	return p >= math.Log10(a.min)-logSnap && p <= math.Log10(a.max)+logSnap
}

// ticks returns the labels for a log axis, in increasing order:
//
//   - every power of ten in the range, thinned to every 2nd, 3rd, ... decade
//     until neighbours are clear of each other, counting from the maximum
//     (else the minimum) when that end of the range is a power of ten;
//   - plus 2x and 5x of each decade where they fit, when unthinned decades
//     alone give fewer than three labels;
//   - a value is never labelled on the first or last cell unless it is
//     within endSlack of that end of the range;
//   - or, if that leaves fewer than two labels (a narrow range inside one
//     decade), evenly spaced positions every step cells as on a linear axis.
func (a logAxis) ticks() []tick {
	if a.step <= 0 || a.size <= 0 || a.last < 0 {
		return nil
	}
	lo := int(math.Ceil(ScaleLog.forward(a.min) - logSnap))
	hi := int(math.Floor(ScaleLog.forward(a.max) + logSnap))

	// A power of ten on the end of the range is worth labelling: the ends
	// are what tell the reader the range.
	endMax := math.Abs(ScaleLog.forward(a.max)-float64(hi)) < logSnap
	endMin := math.Abs(ScaleLog.forward(a.min)-float64(lo)) < logSnap

	// Thin to every stride-th decade, taking the smallest stride that
	// leaves two or more labels clear of each other. final is a last-cell
	// label too long to draw from its own cell. It takes no part in
	// spacing: the caller right-aligns it if there is room left once the
	// other labels are drawn, as for a linear axis.
	var ticks []tick
	var final *tick
	stride := 1
	for ; stride <= max(hi-lo+1, 1); stride++ {
		// Which decades are kept is a choice of phase. Prefer the one that
		// labels the maximum, then the minimum, then gives the most
		// labels; ties go to exponents that are multiples of the stride.
		best := -1
		for phase := 0; phase < stride; phase++ {
			t, f, ok := a.decades(lo, hi, stride, phase)
			if !ok {
				continue
			}
			score := len(t)
			if kept := (hi-phase)%stride == 0; endMax && kept && (f != nil || (len(t) > 0 && t[len(t)-1].pos == a.last)) {
				score += 4 * (hi - lo + 2)
			}
			if kept := (lo-phase)%stride == 0; endMin && kept && len(t) > 0 && t[0].pos == 0 {
				score += 2 * (hi - lo + 2)
			}
			if score > best {
				best, ticks, final = score, t, f
			}
		}
		// an unthinned axis may fill in with 2x and 5x below
		if best >= 0 && (stride == 1 || len(ticks) >= 2) {
			break
		}
	}

	if stride == 1 && len(ticks) < 3 {
		for k := lo - 1; k <= hi; k++ {
			for _, digit := range []int{2, 5} {
				v := logValue(digit, k)
				if !a.inRange(v) {
					continue
				}
				t, drawn := a.tick(v)
				if !drawn || a.overflows(t) {
					continue
				}
				// insert in order if clear of both neighbours
				i := 0
				for i < len(ticks) && ticks[i].value < v {
					i++
				}
				if (i > 0 && !a.clear(ticks[i-1], t)) || (i < len(ticks) && !a.clear(t, ticks[i])) {
					continue
				}
				ticks = append(ticks, tick{})
				copy(ticks[i+1:], ticks[i:])
				ticks[i] = t
			}
		}
	}

	if final != nil {
		ticks = append(ticks, *final)
	}
	if len(ticks) >= 2 {
		return ticks
	}
	return a.evenTicks()
}

// decades returns the labels for the powers of ten 10^k, lo <= k <= hi,
// with k = phase modulo stride. ok is false if two of them are not clear
// of each other. final is as described in ticks.
func (a logAxis) decades(lo, hi, stride, phase int) (ticks []tick, final *tick, ok bool) {
	for k := lo; k <= hi; k++ {
		if (k-phase)%stride != 0 {
			continue
		}
		t, drawn := a.tick(logValue(1, k))
		if !drawn {
			continue
		}
		if a.overflows(t) {
			final = &t
			continue
		}
		if n := len(ticks); n > 0 && !a.clear(ticks[n-1], t) {
			return nil, nil, false
		}
		ticks = append(ticks, t)
	}
	return ticks, final, true
}

// evenTicks labels every step cells from the origin, ending on the last
// position, with the value the log scale puts there.
func (a logAxis) evenTicks() []tick {
	var ticks []tick
	increment := ScaleLog.span(a.min, a.max) / float64(a.size)
	for i := 0; ; i = min(i+a.step, a.last) {
		v := ScaleLog.inverse(ScaleLog.forward(a.min) + increment*float64(i))
		switch {
		case i == 0:
			v = a.min
		case i == a.last:
			v = a.max
		}
		ticks = append(ticks, tick{pos: i, value: v, label: a.format(i, v)})
		if i >= a.last {
			break
		}
	}
	return ticks
}
