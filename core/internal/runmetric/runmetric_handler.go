package runmetric

import (
	"fmt"
	"path/filepath"
	"strings"

	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

// RunMetricHanlder is used to track the run metrics
type RunMetricHanlder struct {
	definedMetrics RunMetricDict
	globMetrics    RunMetricDict
}

// NewMetricHandler creates a new RunMetric
func NewMetricHandler() *RunMetricHanlder {
	return &RunMetricHanlder{
		definedMetrics: make(RunMetricDict),
		globMetrics:    make(RunMetricDict),
	}
}

func (runMetric *RunMetricHanlder) MatchMetric(key string) (*service.MetricRecord, bool) {
	if key == "" {
		return nil, false
	}

	// Skip internal metrics
	if strings.HasPrefix(key, "_") {
		return nil, false
	}

	if metric, ok := runMetric.definedMetrics[key]; ok {
		return metric, true
	}

	if metric, ok := runMetric.findGlobMatch(key); ok {
		metric.Name = key
		metric.GlobName = ""
		metric.Options.Defined = false
		return metric, false
	}

	return nil, false
}

func (runMetric *RunMetricHanlder) findGlobMatch(key string) (*service.MetricRecord, bool) {
	if key == "" {
		return nil, false
	}

	for pattern, metric := range runMetric.globMetrics {
		if match, err := filepath.Match(pattern, key); err != nil {
			// h.logger.CaptureError("error matching metric", err)
			continue
		} else if match {
			return proto.Clone(metric).(*service.MetricRecord), true
		}
	}

	return nil, false
}

func (runMetric *RunMetricHanlder) AddStepMetric(metric *service.MetricRecord) *service.MetricRecord {
	if metric.GetName() == "" {
		return nil
	}

	if metric.GetStepMetric() == "" {
		return nil
	}

	if _, ok := runMetric.definedMetrics[metric.GetStepMetric()]; ok {
		return nil
	}

	stepMetric := &service.MetricRecord{
		Name: metric.GetStepMetric(),
	}

	addMetric(stepMetric, stepMetric.GetName(), &runMetric.definedMetrics)

	return stepMetric
}

func (runMetric *RunMetricHanlder) AddMetric(metric *service.MetricRecord) error {
	// metric can have a glob name or a name
	// TODO: replace glob-name/name with one-of field
	switch {
	case metric.GetGlobName() != "":
		addMetric(metric, metric.GetGlobName(), &runMetric.globMetrics)
		return nil
	case metric.GetName() != "":
		addMetric(metric, metric.GetName(), &runMetric.definedMetrics)
		return nil
	default:
		err := fmt.Errorf("metric must have a name or glob name")
		return err
	}
}
