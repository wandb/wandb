package server

import (
	"errors"
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

// handleStepMetric handles the step metric for a given metric key. If the step metric is not
// defined, it will be added to the defined metrics map.
func (h *Handler) handleStepMetric(key string) {
	if key == "" {
		return
	}

	// already exists no need to add
	if _, defined := h.metricHandler.definedMetrics[key]; defined {
		return
	}

	metric, err := addMetric(key, key, &h.metricHandler.definedMetrics)

	if err != nil {
		h.logger.CaptureError("error adding metric to map", err)
		return
	}

	stepRecord := &service.Record{
		RecordType: &service.Record_Metric{
			Metric: metric,
		},
		Control: &service.Control{
			Local: true,
		},
	}
	h.sendRecord(stepRecord)
}

func (h *Handler) handleMetric(record *service.Record, metric *service.MetricRecord) {
	// metric can have a glob name or a name
	// TODO: replace glob-name/name with one-of field
	switch {
	case metric.GetGlobName() != "":
		if _, err := addMetric(metric, metric.GetGlobName(), &h.metricHandler.globMetrics); err != nil {
			h.logger.CaptureError("error adding metric to map", err)
			return
		}
		h.sendRecord(record)
	case metric.GetName() != "":
		if _, err := addMetric(metric, metric.GetName(), &h.metricHandler.definedMetrics); err != nil {
			h.logger.CaptureError("error adding metric to map", err)
			return
		}
		h.handleStepMetric(metric.GetStepMetric())
		h.sendRecord(record)
	default:
		h.logger.CaptureError("invalid metric", errors.New("invalid metric"))
	}
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
