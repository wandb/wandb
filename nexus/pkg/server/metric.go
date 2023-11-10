package server

import (
	"errors"
	"path/filepath"

	"github.com/wandb/wandb/nexus/internal/nexuslib"
	"github.com/wandb/wandb/nexus/pkg/server/history"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"
)

func (h *Handler) handleDefinedMetric(record *service.Record, metric *service.MetricRecord) {
	if metric.GetXControl().GetOverwrite() {
		h.mm.GetDefinedMetricKeySet().Replace(metric.GetName(), metric)
	} else {
		h.mm.GetDefinedMetricKeySet().Merge(metric.GetName(), metric)
	}

	step := metric.GetStepMetric()
	_, ok := h.mm.GetDefinedMetricKeySet().Get(step)
	if !ok {
		metric := &service.MetricRecord{
			Name: step,
		}
		h.mm.GetDefinedMetricKeySet().Replace(step, metric)
		stepRecord := &service.Record{
			RecordType: &service.Record_Metric{
				Metric: metric,
			},
		}
		h.sendRecordWithControl(stepRecord, func(c *service.Control) {
			c.Local = true
		})
	}
	h.sendRecord(record)
}

func (h *Handler) handleGlobMetric(record *service.Record, metric *service.MetricRecord) {
	if metric.GetXControl().GetOverwrite() {
		h.mm.GetGlobMetricKeySet().Replace(metric.GetGlobName(), metric)
	} else {
		h.mm.GetGlobMetricKeySet().Merge(metric.GetGlobName(), metric)
	}
	h.sendRecord(record)
}

func (h *Handler) handleMetric(record *service.Record, metric *service.MetricRecord) {
	// on the first metric, initialize the metric handler
	if h.mm == nil {
		h.mm = history.NewDefineKeys(
			history.WithDefinedMetricKeySet(
				history.NewKeySet(
					history.WithMerge(
						func(value, newValue *service.MetricRecord) {
							proto.Merge(value, newValue)
						},
					),
				),
			),
			history.WithGlobMetricKeySet(
				history.NewKeySet(
					history.WithMerge(
						func(value, newValue *service.MetricRecord) {
							proto.Merge(value, newValue)
						},
					),
					history.WithMatch[service.MetricRecord](
						filepath.Match,
					),
				),
			),
		)
	}

	// metric can have a glob name or a name
	// TODO: replace glob-name/name with one-of field
	switch {
	case metric.GetGlobName() != "":
		h.handleGlobMetric(record, metric)
	case metric.GetName() != "":
		h.handleDefinedMetric(record, metric)
	default:
		h.logger.CaptureError("invalid metric", errors.New("invalid metric"))
	}
}

type MetricSender struct {
	dm            *history.KeySet[service.MetricRecord]
	metricIndex   map[string]int32
	configMetrics []map[int]interface{}
}

func NewMetricSender() *MetricSender {
	return &MetricSender{
		dm: history.NewKeySet(
			history.WithMerge(
				func(value, newValue *service.MetricRecord) {
					proto.Merge(value, newValue)
				},
			),
		),
		metricIndex:   make(map[string]int32),
		configMetrics: make([]map[int]interface{}, 0),
	}
}

// encodeMetricHints encodes the metric hints for the given metric record. The metric hints
// are used to configure the plots in the UI.
func (s *Sender) encodeMetricHints(_ *service.Record, metric *service.MetricRecord) {

	if metric.GetXControl().GetOverwrite() {
		s.ms.dm.Replace(metric.GetGlobName(), metric)
	} else {
		s.ms.dm.Merge(metric.GetGlobName(), metric)
	}

	if metric.GetStepMetric() != "" {
		index, ok := s.ms.metricIndex[metric.GetStepMetric()]
		if ok {
			metric = proto.Clone(metric).(*service.MetricRecord)
			metric.StepMetric = ""
			metric.StepMetricIndex = index + 1
		}
	}

	encoded := nexuslib.ProtoEncodeToDict(metric)
	if index, ok := s.ms.metricIndex[metric.GetName()]; ok {
		s.ms.configMetrics[index] = encoded
	} else {
		nextIndex := len(s.ms.configMetrics)
		s.ms.configMetrics = append(s.ms.configMetrics, encoded)
		s.ms.metricIndex[metric.GetName()] = int32(nextIndex)
	}
}
