package runmetric

import (
	"github.com/wandb/wandb/core/internal/corelib"
)

// ToRunConfigData returns the data to store in the "m" (metrics) field of
// the run config.
func (mh *MetricHandler) ToRunConfigData() []map[string]any {
	var encodedMetrics []map[string]any
	indexByName := make(map[string]int)

	for name, metric := range mh.definedMetrics {
		encodedMetrics = mh.encodeToRunConfigData(
			name,
			metric,
			encodedMetrics,
			indexByName,
			false,
		)
	}

	for name, metric := range mh.globMetrics {
		encodedMetrics = mh.encodeToRunConfigData(
			name,
			metric,
			encodedMetrics,
			indexByName,
			true,
		)
	}

	return encodedMetrics
}

func (mh *MetricHandler) encodeToRunConfigData(
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

	if metric.Step != "" {
		// Ensure step has an index.
		encodedMetrics = mh.encodeToRunConfigData(
			metric.Step,
			// If it doesn't exist, then it's an empty definition which is OK.
			mh.definedMetrics[metric.Step],
			encodedMetrics,
			indexByName,
			// Step metrics are never interpreted as globs.
			false,
		)

		record.StepMetric = ""
		record.StepMetricIndex = int32(indexByName[metric.Step] + 1)
	}

	return encodedMetrics
}
