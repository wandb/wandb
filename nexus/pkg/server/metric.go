package server

import (
	"errors"
	"github.com/wandb/wandb/nexus/internal/nexuslib"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"
	"path/filepath"
	"strings"
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

func (mh *MetricHandler) matchGlobMetrics(key string) *service.MetricRecord {
	metric, ok := mh.definedMetrics[key]
	if ok {
		return nil
	}

	for pattern, globMetric := range mh.globMetrics {
		if match, err := filepath.Match(pattern, key); err != nil {
			//h.logger.CaptureError("error matching metric", err)
			continue
		} else if match {
			metric = proto.Clone(globMetric).(*service.MetricRecord)
			metric.Name = key
			metric.Options.Defined = false
			metric.GlobName = ""
			return metric
		}
	}
	return nil
}

func (h *Handler) handleStepMetric(key string) {
	if key == "" {
		return
	}

	// already exists no need to add
	if _, ok := h.mh.definedMetrics[key]; ok {
		return
	}

	metric, err := addMetric(key, key, &h.mh.definedMetrics)

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
	if h.mh == nil {
		h.mh = NewMetricHandler()
	}

	if metric.GetGlobName() != "" {
		if _, err := addMetric(metric, metric.GetGlobName(), &h.mh.globMetrics); err != nil {
			h.logger.CaptureError("error adding metric to map", err)
		}
		return
	}

	if metric.GetName() != "" {
		if _, err := addMetric(metric, metric.GetName(), &h.mh.definedMetrics); err != nil {
			h.logger.CaptureError("error adding metric to map", err)
			return
		}

		h.handleStepMetric(metric.GetStepMetric())
		h.sendRecord(record)
	}
}

func (h *Handler) handleMetricHistory(history *service.HistoryRecord) {
	// This means that there are no definedMetrics to send hence we can return early
	if h.mh == nil {
		return
	}

	for _, item := range history.GetItem() {
		// TODO: add recursion for nested history items

		// ignore internal definedMetrics
		if strings.HasPrefix(item.Key, "_") {
			continue
		}

		metric := h.mh.matchGlobMetrics(item.Key)

		if metric != nil {
			record := &service.Record{
				RecordType: &service.Record_Metric{
					Metric: metric,
				},
				Control: &service.Control{
					Local: true,
				},
			}
			h.handleMetric(record, metric)

			if metric.GetOptions().GetStepSync() && metric.GetStepMetric() != "" {
				// TODO replace with the correct summary when implemented
				if value, ok := h.consolidatedSummary[metric.GetStepMetric()]; ok {
					mItem := &service.HistoryItem{
						Key:       metric.GetStepMetric(),
						ValueJson: value,
					}
					history.Item = append(history.Item, mItem)
				}
			}
		}
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

func (s *Sender) handleMetricIndex(_ *service.Record, metric *service.MetricRecord) {

	_, err := addMetric(metric, metric.GetName(), &s.ms.definedMetrics)
	if err != nil {
		return
	}

	if metric.GetStepMetric() != "" {
		index, ok := s.ms.metricIndex[metric.GetStepMetric()]
		if ok {
			metric = proto.Clone(metric).(*service.MetricRecord)
			metric.StepMetric = ""
			metric.StepMetricIndex = index + 1
		}
	}

	encodeMetric := nexuslib.ProtoEncodeToDict(metric)
	if index, ok := s.ms.metricIndex[metric.GetName()]; ok {
		s.ms.configMetrics[index] = encodeMetric
	} else {
		nextIndex := len(s.ms.configMetrics)
		s.ms.configMetrics = append(s.ms.configMetrics, encodeMetric)
		s.ms.metricIndex[metric.GetName()] = int32(nextIndex)
	}
}
