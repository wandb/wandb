package runsummary

import "github.com/wandb/simplejsonext"

// metricSummary is the summary value of a single metric.
//
// The zero value is an empty summary.
type metricSummary struct {
	latest any
	min    float64
	max    float64
	total  float64
	count  int

	// track is the list of summary values to emit.
	//
	// If empty, the latest value is used. Otherwise, the metric's summary is
	// a dictionary containing the requested values.
	track SummaryTypeFlags

	// noSummary disables any summary output for the metric at all.
	noSummary bool

	// hasData is whether any summary data has been accumulated.
	hasData bool
}

func (ms *metricSummary) Clear() {
	ms.latest = nil
	ms.hasData = false
}

// SetExplicit sets an explicit summary value for the metric.
//
// This resets any configured summary types.
func (ms *metricSummary) SetExplicit(value any) {
	ms.latest = value
	ms.track = Unset
	ms.hasData = true
}

// UpdateFloat updates the metric's summary with the latest value
// when it is a float.
func (ms *metricSummary) UpdateFloat(value float64) {
	ms.latest = value
	ms.hasData = true

	if ms.count > 0 {
		ms.min = min(ms.min, value)
		ms.max = max(ms.max, value)
	} else {
		ms.min = value
		ms.max = value
	}
	ms.total += value
	ms.count++
}

// UpdateInt updates the metric's summary with the latest value
// when it is an integer.
func (ms *metricSummary) UpdateInt(value int64) {
	ms.latest = value
	ms.hasData = true

	if ms.count > 0 {
		ms.min = min(ms.min, float64(value))
		ms.max = max(ms.max, float64(value))
	} else {
		ms.min = float64(value)
		ms.max = float64(value)
	}
	ms.total += float64(value)
	ms.count++
}

// UpdateOther updates the metric's summary with the latest value
// when it's not a number.
func (ms *metricSummary) UpdateOther(value any) {
	ms.latest = value
	ms.hasData = true
}

// ToMarshallableValue returns the metric's summary as
// a JSON-marshallable type.
//
// Returns nil if there is no summary.
func (ms *metricSummary) ToMarshallableValue() any {
	if ms.noSummary || !ms.hasData {
		return nil
	}

	if ms.track.IsEmpty() {
		return ms.latest
	}

	summary := make(map[string]any)
	if ms.track.HasAny(Latest) {
		summary["last"] = ms.latest
	}
	if ms.track.HasAny(Max) {
		summary["max"] = ms.max
	}
	if ms.track.HasAny(Min) {
		summary["min"] = ms.min
	}
	if ms.track.HasAny(Mean) {
		summary["mean"] = ms.total / float64(ms.count)
	}

	return summary
}

// ToExtendedJSON serializes the summary to a JSON string supporting
// +-Infinity and NaN.
//
// Returns an empty string if the metric should have no summary.
func (ms *metricSummary) ToExtendedJSON() (string, error) {
	jsonSummary := ms.ToMarshallableValue()

	if jsonSummary == nil {
		return "", nil
	} else {
		return simplejsonext.MarshalToString(jsonSummary)
	}
}
