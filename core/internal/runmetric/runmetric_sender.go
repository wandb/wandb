package runmetric

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

type RunMetricSender struct {
	metrics RunMetricDict
	indeces map[string]int32
	Config  []map[int]interface{}
}

func NewRunMetricSender() *RunMetricSender {
	return &RunMetricSender{
		metrics: make(RunMetricDict),
		indeces: make(map[string]int32),
		Config:  make([]map[int]interface{}, 0),
	}
}

func (runMetric *RunMetricSender) EncodeConfigHints(metric *service.MetricRecord) error {
	if metric.GetName() == "" {
		err := fmt.Errorf("metric name is required")
		return err
	}

	if metric.GetGlobName() != "" {
		err := fmt.Errorf("glob name is not allowed")
		return err
	}

	addMetric(metric, metric.GetName(), &runMetric.metrics)

	// Check if the metric has a step metric
	// If it does, we need to increment the step metric index
	// and remove the step metric from the metric
	if metric.GetStepMetric() != "" {
		index, ok := runMetric.indeces[metric.GetStepMetric()]
		if ok {
			metric = proto.Clone(metric).(*service.MetricRecord)
			metric.StepMetric = ""
			metric.StepMetricIndex = index + 1
		}
	}

	encoded := corelib.ProtoEncodeToDict(metric)
	if index, ok := runMetric.indeces[metric.GetName()]; ok {
		runMetric.Config[index] = encoded
	} else {
		next := int32(len(runMetric.Config))
		runMetric.Config = append(runMetric.Config, encoded)
		runMetric.indeces[metric.GetName()] = next
	}
	return nil
}
