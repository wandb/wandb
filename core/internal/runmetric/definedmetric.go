package runmetric

import (
	"github.com/wandb/wandb/core/internal/runsummary"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type metricGoal uint64

const (
	metricGoalUnset metricGoal = iota
	metricGoalMinimize
	metricGoalMaximize
)

type definedMetric struct {
	// SyncStep is whether to automatically insert values of this metric's
	// step metric into the run history.
	SyncStep bool

	// Step is the name of the associated step metric, if any.
	Step string

	// IsHidden is whether the metric is hidden in the UI.
	IsHidden bool

	// IsExplicit is whether the metric was defined explicitly or through
	// a matched glob.
	IsExplicit bool

	// NoSummary is whether to skip tracking a summary for the metric.
	NoSummary bool

	// SummaryTypes is the set of summary statistics to track.
	SummaryTypes runsummary.SummaryTypeFlags

	// MetricGoal is how to interpret the "best" summary type.
	MetricGoal metricGoal
}

// With returns this metric definition updated with the information
// in the proto.
func (m definedMetric) With(
	record *spb.MetricRecord,
) definedMetric {
	// record.Options is currently always non-nil because of the "defined"
	// field, so we do not have a mechanism of updating SyncStep or
	// IsHidden to `false` after it has been set to `true`.
	m.SyncStep = m.SyncStep || record.GetOptions().GetStepSync()
	m.IsHidden = m.IsHidden || record.GetOptions().GetHidden()

	if len(record.StepMetric) > 0 {
		m.Step = record.StepMetric
	}

	if record.Summary != nil {
		m.NoSummary = record.Summary.None

		m.SummaryTypes = 0

		// TODO: handle "best" and "copy" summary settings
		if record.Summary.Min {
			m.SummaryTypes |= runsummary.Min
		}
		if record.Summary.Max {
			m.SummaryTypes |= runsummary.Max
		}
		if record.Summary.Mean {
			m.SummaryTypes |= runsummary.Mean
		}
		if record.Summary.Last {
			m.SummaryTypes |= runsummary.Latest
		}
	}

	switch record.Goal {
	case spb.MetricRecord_GOAL_MAXIMIZE:
		m.MetricGoal = metricGoalMaximize
	case spb.MetricRecord_GOAL_MINIMIZE:
		m.MetricGoal = metricGoalMinimize
	}

	if len(record.Name) > 0 {
		m.IsExplicit = true
	}

	return m
}

// ToRecord returns a MetricRecord representing this metric.
func (m definedMetric) ToRecord(name string) *spb.MetricRecord {
	rec := &spb.MetricRecord{
		Name:       name,
		StepMetric: m.Step,
		Options: &spb.MetricOptions{
			StepSync: m.SyncStep,
			Hidden:   m.IsHidden,
			Defined:  m.IsExplicit,
		},

		// definedMetric is always a complete definition rather than
		// a partial update.
		XControl: &spb.MetricControl{Overwrite: true},
	}

	rec.Summary = &spb.MetricSummary{
		None: m.NoSummary,
	}
	if m.SummaryTypes.HasAny(runsummary.Min) {
		rec.Summary.Min = true
	}
	if m.SummaryTypes.HasAny(runsummary.Max) {
		rec.Summary.Max = true
	}
	if m.SummaryTypes.HasAny(runsummary.Mean) {
		rec.Summary.Mean = true
	}
	if m.SummaryTypes.HasAny(runsummary.Latest) {
		rec.Summary.Last = true
	}

	switch m.MetricGoal {
	case metricGoalMaximize:
		rec.Goal = spb.MetricRecord_GOAL_MAXIMIZE
	case metricGoalMinimize:
		rec.Goal = spb.MetricRecord_GOAL_MINIMIZE
	}

	return rec
}
