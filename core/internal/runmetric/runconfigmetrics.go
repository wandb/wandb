package runmetric

import (
	"github.com/wandb/wandb/core/internal/corelib"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// RunConfigMetrics tracks a run's defined metrics in the run's config.
type RunConfigMetrics struct {
	// handler parses MetricRecords.
	handler *MetricHandler

	expandGlobMetrics bool
}

func NewRunConfigMetrics(expandGlobMetrics bool) *RunConfigMetrics {
	return &RunConfigMetrics{
		handler:           New(),
		expandGlobMetrics: expandGlobMetrics,
	}
}

// ProcessRecord updates metric definitions.
func (rcm *RunConfigMetrics) ProcessRecord(record *spb.MetricRecord) error {
	return rcm.handler.ProcessRecord(record)
}

// ToRunConfigData returns the data to store in the "m" (metrics) field of
// the run config.
//
// May succeed partially, in which case the returned slice contains all
// metrics that were successfully encoded and the error is non-nil.
func (rcm *RunConfigMetrics) ToRunConfigData() []map[string]any {
	var encodedMetrics []map[string]any
	indexByName := make(map[string]int)

	for name, metric := range rcm.handler.definedMetrics {
		encodedMetrics = rcm.encodeToRunConfigData(
			name,
			metric,
			encodedMetrics,
			indexByName,
			false,
		)
	}

	if rcm.expandGlobMetrics {
		for name, metric := range rcm.handler.globMetrics {
			encodedMetrics = rcm.encodeToRunConfigData(
				name,
				metric,
				encodedMetrics,
				indexByName,
				true,
			)
		}
	}

	return encodedMetrics
}

func (rcm *RunConfigMetrics) encodeToRunConfigData(
	name string,
	metric definedMetric,
	encodedMetrics []map[string]any,
	indexByName map[string]int,
	isGlob bool,
) []map[string]any {
	// Early exit if we already added the metric to the array.
	if _, processed := indexByName[name]; processed {
		return encodedMetrics
	}

	index := len(encodedMetrics)
	indexByName[name] = index

	// Save a spot in encodedMetrics, but encode `record` after we've
	// fully built it at the end of the method.
	encodedMetrics = append(encodedMetrics, nil)

	record := metric.ToRecord(name, isGlob)
	defer func() {
		encodedMetrics[index] = corelib.ProtoEncodeToDict(record)
	}()

	if len(metric.Step) > 0 {
		// Ensure step has an index.
		encodedMetrics = rcm.encodeToRunConfigData(
			metric.Step,
			// If it doesn't exist, then it's an empty definition which is OK.
			rcm.handler.definedMetrics[metric.Step],
			encodedMetrics,
			indexByName,
			// operating under the assumption that the step metric is
			// never a glob metric.
			false,
		)

		record.StepMetric = ""
		record.StepMetricIndex = int32(indexByName[metric.Step] + 1)
	}

	return encodedMetrics
}
