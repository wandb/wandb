package runmetric

import (
	"errors"
	"fmt"

	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/pkg/service"
)

// RunConfigMetrics tracks a run's defined metrics in the run's config.
type RunConfigMetrics struct {
	// handler parses MetricRecords.
	handler *MetricHandler
}

func NewRunConfigMetrics() *RunConfigMetrics {
	return &RunConfigMetrics{
		handler: New(),
	}
}

// ProcessRecord updates metric definitions.
func (rcm *RunConfigMetrics) ProcessRecord(record *service.MetricRecord) error {
	return rcm.handler.ProcessRecord(record)
}

// ToRunConfigData returns the data to store in the "m" (metrics) field of
// the run config.
//
// May succeed partially, in which case the returned slice contains all
// metrics that were successfully encoded and the error is non-nil.
func (rcm *RunConfigMetrics) ToRunConfigData() ([]map[string]any, error) {
	var errs []error
	var encodedMetrics []map[string]any
	indexByName := make(map[string]int)

	for name, metric := range rcm.handler.definedMetrics {
		if !metric.HasUIHints() {
			continue
		}

		var err error
		encodedMetrics, err = rcm.encodeToRunConfigData(
			name,
			metric,
			encodedMetrics,
			indexByName,
			make(map[string]struct{}),
		)

		if err != nil {
			errs = append(errs, err)
		}
	}

	return encodedMetrics, errors.Join(errs...)
}

func (rcm *RunConfigMetrics) encodeToRunConfigData(
	name string,
	metric definedMetric,
	encodedMetrics []map[string]any,
	indexByName map[string]int,
	seenMetrics map[string]struct{},
) ([]map[string]any, error) {
	// Early exit if we already added the metric to the array.
	if _, processed := indexByName[name]; processed {
		return encodedMetrics, nil
	}

	// Prevent infinite loops (note: indexByName is updated at the
	// end of the method, so it's not suitable for this purpose.)
	if _, seen := seenMetrics[name]; seen {
		return encodedMetrics, fmt.Errorf("metric '%s' references itself", name)
	}
	seenMetrics[name] = struct{}{}

	record := metric.ToRecord(name)

	// Encode the step metric first because we need to pass the index
	// to the UI.
	if len(metric.Step) > 0 {
		var err error
		encodedMetrics, err = rcm.encodeToRunConfigData(
			metric.Step,
			// If it doesn't exist, then it's an empty definition which is OK.
			rcm.handler.definedMetrics[metric.Step],
			encodedMetrics,
			indexByName,
			seenMetrics,
		)

		if err != nil {
			return encodedMetrics, fmt.Errorf(
				"failed to encode metric '%s': %v",
				name,
				err,
			)
		}

		record.StepMetric = ""
		record.StepMetricIndex = int32(indexByName[metric.Step] + 1)
	}

	indexByName[name] = len(encodedMetrics)
	return append(encodedMetrics, corelib.ProtoEncodeToDict(record)), nil
}
