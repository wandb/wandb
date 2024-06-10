package server

import (
	"errors"
	"fmt"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

type MetricHandler struct {
	definedMetrics map[string]*service.MetricRecord
	globMetrics    map[string]*service.MetricRecord
}

func NewMetricHandler() *MetricHandler {
	return &MetricHandler{
		definedMetrics: make(map[string]*service.MetricRecord),
		globMetrics:    make(map[string]*service.MetricRecord),
	}
}

// addMetric adds a metric to the target map. If the metric already exists, it will be merged
// with the existing metric. If the overwrite flag is set, the metric will be overwritten.
func addMetric(arg interface{}, key string, target *map[string]*service.MetricRecord) (*service.MetricRecord, error) {
	var metric *service.MetricRecord

	switch v := arg.(type) {
	case string:
		metric = &service.MetricRecord{
			Name: v,
		}
	case *service.MetricRecord:
		metric = v
	default:
		// Handle invalid input
		return nil, errors.New("invalid input")
	}

	if metric.GetXControl().GetOverwrite() {
		(*target)[key] = metric
	} else {
		if existingMetric, ok := (*target)[key]; ok {
			proto.Merge(existingMetric, metric)
		} else {
			(*target)[key] = metric
		}
	}
	return metric, nil
}

// createMatchingGlobMetric check if a key matches a glob pattern, if it does create a new defined metric
// based on the glob metric and return it.
func (mh *MetricHandler) createMatchingGlobMetric(key string) *service.MetricRecord {

	fmt.Printf("metricHandler: %v\n", *mh)
	for pattern, globMetric := range mh.globMetrics {
		fmt.Printf("    pattern: %v, globMetric: %v\n", pattern, *globMetric)
	}
	for pattern, definedMetric := range mh.definedMetrics {
		fmt.Printf("    pattern: %v, definedMetric: %v\n", pattern, *definedMetric)
	}

	for pattern, globMetric := range mh.globMetrics {
		if match, err := filepath.Match(pattern, key); err != nil {
			// h.logger.CaptureError("error matching metric", err)
			continue
		} else if match {
			metric := proto.Clone(globMetric).(*service.MetricRecord)
			metric.Name = key
			metric.Options.Defined = false
			metric.GlobName = ""
			return metric
		}
	}
	return nil
}

type MetricSender struct {
	definedMetrics map[string]*service.MetricRecord
	metricIndex    map[string]int32
	configMetrics  []map[int]interface{}
}

func NewMetricSender() *MetricSender {
	return &MetricSender{
		definedMetrics: make(map[string]*service.MetricRecord),
		metricIndex:    make(map[string]int32),
		configMetrics:  make([]map[int]interface{}, 0),
	}
}

// encodeMetricHints encodes the metric hints for the given metric record. The metric hints
// are used to configure the plots in the UI.
func (s *Sender) encodeMetricHints(_ *service.Record, metric *service.MetricRecord) {

	_, err := addMetric(metric, metric.GetName(), &s.metricSender.definedMetrics)
	if err != nil {
		return
	}

	if metric.GetStepMetric() != "" {
		index, ok := s.metricSender.metricIndex[metric.GetStepMetric()]
		if ok {
			metric = proto.Clone(metric).(*service.MetricRecord)
			metric.StepMetric = ""
			metric.StepMetricIndex = index + 1
		}
	}

	encodeMetric := corelib.ProtoEncodeToDict(metric)
	if index, ok := s.metricSender.metricIndex[metric.GetName()]; ok {
		s.metricSender.configMetrics[index] = encodeMetric
	} else {
		nextIndex := len(s.metricSender.configMetrics)
		s.metricSender.configMetrics = append(s.metricSender.configMetrics, encodeMetric)
		s.metricSender.metricIndex[metric.GetName()] = int32(nextIndex)
	}
}
