package handler

import (
	"errors"
	"path/filepath"

	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
	"google.golang.org/protobuf/proto"
)

type Metrics struct {
	Defined map[string]*pb.MetricRecord
	Glob    map[string]*pb.MetricRecord
}

func NewMetrics() *Metrics {
	return &Metrics{
		Defined: make(map[string]*pb.MetricRecord),
		Glob:    make(map[string]*pb.MetricRecord),
	}
}

// AddMetric adds a metric to the target map. If the metric already exists, it will be merged
// with the existing metric. If the overwrite flag is set, the metric will be overwritten.
func AddMetric(arg interface{}, key string, target *map[string]*pb.MetricRecord) (*pb.MetricRecord, error) {
	var metric *pb.MetricRecord

	switch v := arg.(type) {
	case string:
		metric = &pb.MetricRecord{
			Name: v,
		}
	case *pb.MetricRecord:
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
func (mh *Metrics) createMatchingGlobMetric(key string) *pb.MetricRecord {
	for pattern, globMetric := range mh.Glob {
		if match, err := filepath.Match(pattern, key); err != nil {
			// h.logger.CaptureError("error matching metric", err)
			continue
		} else if match {
			metric := proto.Clone(globMetric).(*pb.MetricRecord)
			metric.Name = key
			metric.Options.Defined = false
			metric.GlobName = ""
			return metric
		}
	}
	return nil
}
