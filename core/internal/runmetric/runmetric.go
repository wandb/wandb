package runmetric

import (
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

type RunMetricDict = map[string]*service.MetricRecord

func addMetric(
	metric *service.MetricRecord,
	key string,
	target *RunMetricDict,
) {
	if metric.GetXControl().GetOverwrite() {
		(*target)[key] = metric
		return
	}
	if existingMetric, ok := (*target)[key]; ok {
		proto.Merge(existingMetric, metric)
	} else {
		(*target)[key] = metric
	}
}
