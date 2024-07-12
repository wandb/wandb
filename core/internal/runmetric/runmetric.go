package runmetric

import (
	"errors"
	"path/filepath"
	"strings"

	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

type MetricHandler struct {
	metricDefs     map[string]*service.MetricRecord
	globMetricDefs map[string]*service.MetricRecord
}

func NewMetricHandler() *MetricHandler {
	return &MetricHandler{
		metricDefs:     make(map[string]*service.MetricRecord),
		globMetricDefs: make(map[string]*service.MetricRecord),
	}
}

// Exists returns whether a non-glob metric is defined.
func (mh *MetricHandler) Exists(key string) bool {
	_, exists := mh.metricDefs[key]
	return exists
}

// InsertStepMetrics inserts an automatic step metric for every defined
// metric with step_sync set to true.
//
// TODO: Remove the 'summary' parameter from 'InsertStepMetrics'.
// The 'summary' parameter is used by the old implementation, which is
// to be refactored.
func (mh *MetricHandler) InsertStepMetrics(
	history *runhistory.RunHistory,
	summary *runsummary.RunSummary,
) {
	for _, metricDef := range mh.metricDefs {
		// Skip any metrics that do not need to be synced.
		if metricDef.StepMetric == "" || !metricDef.Options.GetStepSync() {
			continue
		}

		// Skip if the step is already set.
		if history.Contains(metricDef.StepMetric) {
			continue
		}

		// Skip if the metric doesn't show up in history.
		if !history.Contains(metricDef.Name) {
			continue
		}

		// TODO: Insert the latest value.
		mh.hackInsertLatestValue(metricDef.StepMetric, history, summary)
	}
}

func (mh *MetricHandler) hackInsertLatestValue(
	stepMetricKey string,
	history *runhistory.RunHistory,
	summary *runsummary.RunSummary,
) {
	value, exists := summary.Tree()[stepMetricKey]
	if !exists {
		return
	}

	switch x := value.(type) {
	case int64:
		history.SetInt(stepMetricKey, x)
	case float64:
		history.SetFloat(stepMetricKey, x)
	case string:
		history.SetString(stepMetricKey, x)
	}
}

// CreateGlobMetrics returns new metric definitions created by matching
// glob metrics to the history.
func (mh *MetricHandler) CreateGlobMetrics(
	history *runhistory.RunHistory,
) []*service.MetricRecord {
	var newMetrics []*service.MetricRecord

	history.ForEachKey(func(key string) bool {
		// Skip metrics prefixed by an underscore, which are internal to W&B.
		if strings.HasPrefix(key, "_") {
			return true
		}

		_, isKnown := mh.metricDefs[key]
		if isKnown {
			return true
		}

		metric := mh.matchGlobMetric(key)
		if metric != nil {
			mh.metricDefs[key] = metric
			newMetrics = append(newMetrics, metric)
		}

		return true
	})

	return newMetrics
}

// matchGlobMetric returns a new metric definition if the key matches
// a glob metric, and otherwise returns nil.
func (mh *MetricHandler) matchGlobMetric(key string) *service.MetricRecord {
	for glob, metric := range mh.globMetricDefs {
		match, err := filepath.Match(glob, key)

		if err != nil || !match {
			continue
		}

		return &service.MetricRecord{
			Name: key,

			StepMetric:      metric.StepMetric,
			StepMetricIndex: metric.StepMetricIndex,

			Options: &service.MetricOptions{
				StepSync: metric.Options.StepSync,
				Hidden:   metric.Options.Hidden,
				Defined:  false,
			},

			Summary:  metric.Summary,
			Goal:     metric.Goal,
			XControl: metric.XControl,
			XInfo:    metric.XInfo,
		}
	}
	return nil
}

// AddMetric registers a new defined metric.
func (mh *MetricHandler) AddMetric(metric *service.MetricRecord) {
	switch {
	case metric.GlobName != "":
		prev, exists := mh.globMetricDefs[metric.GlobName]

		if metric.GetXControl().GetOverwrite() || !exists {
			mh.globMetricDefs[metric.GlobName] = metric
		} else {
			// TODO: No!!!
			proto.Merge(prev, metric)
		}

	case metric.Name != "":
		prev, exists := mh.metricDefs[metric.Name]

		if metric.GetXControl().GetOverwrite() || !exists {
			mh.metricDefs[metric.Name] = metric
		} else {
			// TODO: No!!!
			proto.Merge(prev, metric)
		}
	}
}

func (mh *MetricHandler) HackGetDefinedMetrics() map[string]*service.MetricRecord {
	return mh.metricDefs
}

func (mh *MetricHandler) HackGetGlobMetrics() map[string]*service.MetricRecord {
	return mh.globMetricDefs
}

type MetricSender struct {
	DefinedMetrics map[string]*service.MetricRecord
	MetricIndex    map[string]int32
	ConfigMetrics  []map[int]interface{}
}

func NewMetricSender() *MetricSender {
	return &MetricSender{
		DefinedMetrics: make(map[string]*service.MetricRecord),
		MetricIndex:    make(map[string]int32),
		ConfigMetrics:  make([]map[int]interface{}, 0),
	}
}

func (ms *MetricSender) AddNonGlobMetric(metric *service.MetricRecord) error {
	if metric.Name == "" {
		return errors.New("runmetric: expected non-empty name")
	}

	prev, exists := ms.DefinedMetrics[metric.Name]

	if metric.GetXControl().GetOverwrite() || !exists {
		ms.DefinedMetrics[metric.Name] = metric
	} else {
		// TODO: No!!!
		proto.Merge(prev, metric)
	}

	return nil
}
