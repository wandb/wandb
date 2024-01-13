package sender

import (
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type MetricSender struct {
	definedMetrics map[string]*pb.MetricRecord
	metricIndex    map[string]int32
	configMetrics  []map[int]interface{}
}

func NewMetricSender() *MetricSender {
	return &MetricSender{
		definedMetrics: make(map[string]*pb.MetricRecord),
		metricIndex:    make(map[string]int32),
		configMetrics:  make([]map[int]interface{}, 0),
	}
}
