package leet

import (
	"math"
	"time"
)

// stepTimeline maps a run's history steps to the wall-clock times they were
// logged at, in both directions. Rows are appended in logging order, so
// both slices stay sorted.
type stepTimeline struct {
	steps []float64
	times []float64 // unix seconds
}

func (t *stepTimeline) add(rows MetricData) {
	t.steps = append(t.steps, rows.X...)
	t.times = append(t.times, rows.Y...)
}

// timeAt returns when the history row nearest to step was logged.
func (t *stepTimeline) timeAt(step float64) (time.Time, bool) {
	i := nearestIndexForX(t.steps, step)
	if i < 0 {
		return time.Time{}, false
	}
	return unixSeconds(t.times[i]), true
}

// stepAt returns the step of the history row logged nearest to tm.
func (t *stepTimeline) stepAt(tm time.Time) (float64, bool) {
	i := nearestIndexForX(t.times, float64(tm.UnixNano())/1e9)
	if i < 0 {
		return 0, false
	}
	return t.steps[i], true
}

func unixSeconds(sec float64) time.Time {
	whole, frac := math.Modf(sec)
	return time.Unix(int64(whole), int64(frac*1e9))
}
