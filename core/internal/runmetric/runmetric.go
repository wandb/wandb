package runmetric

import (
	"errors"
	"fmt"
	"path/filepath"

	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

type MetricHandler struct {
	DefinedMetrics map[string]*service.MetricRecord
	GlobMetrics    map[string]*service.MetricRecord
}

func NewMetricHandler() *MetricHandler {
	return &MetricHandler{
		DefinedMetrics: make(map[string]*service.MetricRecord),
		GlobMetrics:    make(map[string]*service.MetricRecord),
	}
}

// createMatchingGlobMetric check if a key matches a glob pattern, if it does create a new defined metric
// based on the glob metric and return it.
func (mh *MetricHandler) CreateMatchingGlobMetric(key string) *service.MetricRecord {

	fmt.Printf("metricHandler: %v\n", *mh)
	// for pattern, globMetric := range mh.globMetrics {
	// 	fmt.Printf("    pattern: %v, globMetric: %v\n", pattern, *globMetric)
	// }
	// for pattern, definedMetric := range mh.definedMetrics {
	// 	fmt.Printf("    pattern: %v, definedMetric: %v\n", pattern, *definedMetric)
	// }

	for pattern, globMetric := range mh.GlobMetrics {
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

// AddMetric adds a metric to the target map. If the metric already exists, it will be merged
// with the existing metric. If the overwrite flag is set, the metric will be overwritten.
func AddMetric(arg interface{}, key string, target *map[string]*service.MetricRecord) (*service.MetricRecord, error) {
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
