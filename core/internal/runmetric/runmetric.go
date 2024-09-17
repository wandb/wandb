package runmetric

import (
	"errors"
	"path/filepath"
	"strings"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runsummary"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type MetricHandler struct {
	definedMetrics map[string]definedMetric
	globMetrics    map[string]definedMetric

	// latestStep tracks the latest value of every step metric.
	latestStep map[string]float64
}

func New() *MetricHandler {
	return &MetricHandler{
		definedMetrics: make(map[string]definedMetric),
		globMetrics:    make(map[string]definedMetric),
		latestStep:     make(map[string]float64),
	}
}

// Exists reports whether a non-glob metric is defined.
func (mh *MetricHandler) Exists(key string) bool {
	_, exists := mh.definedMetrics[key]
	return exists
}

// ProcessRecord updates metric definitions.
func (mh *MetricHandler) ProcessRecord(record *spb.MetricRecord) error {
	if len(record.StepMetric) > 0 {
		if _, ok := mh.latestStep[record.StepMetric]; !ok {
			mh.latestStep[record.StepMetric] = 0
		}
	}

	var metricByKey map[string]definedMetric
	var key string
	switch {
	case len(record.Name) > 0:
		metricByKey = mh.definedMetrics
		key = record.Name
	case len(record.GlobName) > 0:
		metricByKey = mh.globMetrics
		key = record.GlobName
	case len(record.StepMetric) > 0:
		// This is an explicit X axis; nothing to do.
		return nil
	default:
		return errors.New("runmetric: name, glob_name or step_metric must be set")
	}

	var prev definedMetric
	if !record.GetXControl().GetOverwrite() {
		prev = metricByKey[key]
	}

	updated := prev.With(record)
	metricByKey[key] = updated

	return nil
}

// UpdateSummary updates the statistics tracked in the run summary
// for the given metric.
func (mh *MetricHandler) UpdateSummary(
	name string,
	summary *runsummary.RunSummary,
) {
	metric, ok := mh.definedMetrics[name]

	if !ok {
		return
	}

	if len(name) == 0 {
		return
	}
	parts := strings.Split(name, ".")
	path := pathtree.PathOf(parts[0], parts[1:]...)

	summary.ConfigureMetric(path, metric.NoSummary, metric.SummaryTypes)
}

// UpdateMetrics creates new metric definitions from globs that
// match the new history value and updates the latest value tracked
// for every metric used as a custom step.
//
// Returns any new metrics that were created.
func (mh *MetricHandler) UpdateMetrics(
	history *runhistory.RunHistory,
) []*spb.MetricRecord {
	for key := range mh.latestStep {
		if len(key) == 0 {
			continue
		}
		keyLabels := strings.Split(key, ".")
		keyPath := pathtree.PathOf(keyLabels[0], keyLabels[1:]...)

		latest, ok := history.GetNumber(keyPath)
		if !ok {
			continue
		}

		mh.latestStep[key] = latest
	}

	return mh.createGlobMetrics(history)
}

// InsertStepMetrics inserts an automatic step metric for every defined
// metric with step_sync set to true.
func (mh *MetricHandler) InsertStepMetrics(
	history *runhistory.RunHistory,
) {
	history.ForEachKey(func(path pathtree.TreePath) bool {
		key := strings.Join(path.Labels(), ".")
		metricDef, ok := mh.definedMetrics[key]
		if !ok {
			return true
		}

		// Skip any metrics that do not need to be synced.
		if metricDef.Step == "" || !metricDef.SyncStep {
			return true
		}

		stepMetricLabels := strings.Split(metricDef.Step, ".")
		stepMetricPath := pathtree.PathOf(
			stepMetricLabels[0],
			stepMetricLabels[1:]...,
		)

		// Skip if the step is already set.
		if history.Contains(stepMetricPath) {
			return true
		}
		latest, ok := mh.latestStep[metricDef.Step]
		// This should never happen, but we'll skip the metric if it does.
		if !ok {
			return true
		}
		history.SetFloat(stepMetricPath, latest)
		return true
	})
}

// createGlobMetrics returns new metric definitions created by matching
// glob metrics to the history.
func (mh *MetricHandler) createGlobMetrics(
	history *runhistory.RunHistory,
) []*spb.MetricRecord {
	var newMetrics []*spb.MetricRecord

	history.ForEachKey(func(path pathtree.TreePath) bool {
		key := strings.Join(path.Labels(), ".")

		// Skip metrics prefixed by an underscore, which are internal to W&B.
		if strings.HasPrefix(key, "_") {
			return true
		}

		_, isKnown := mh.definedMetrics[key]
		if isKnown {
			return true
		}

		metric, ok := mh.matchGlobMetric(key)
		if ok {
			mh.definedMetrics[key] = metric
			newMetrics = append(newMetrics, metric.ToRecord(key))
		}

		return true
	})

	return newMetrics
}

// matchGlobMetric returns a new metric definition if the key matches
// a glob metric, and otherwise returns nil.
func (mh *MetricHandler) matchGlobMetric(key string) (definedMetric, bool) {
	for glob, metric := range mh.globMetrics {
		match, err := filepath.Match(glob, key)

		if err != nil || !match {
			continue
		}

		return metric, true
	}

	return definedMetric{}, false
}
