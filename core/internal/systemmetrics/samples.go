package systemmetrics

import (
	"sort"
	"strings"

	"google.golang.org/protobuf/reflect/protoreflect"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Sample is one measured value of a record together with what a chart needs
// to place it: the schema field it came from, that field's MetricInfo, and
// the identity of the thing measured.
type Sample struct {
	// Path is the dotted proto field path from the record root, for example
	// "accelerators.temperature_c" or "host.disk_io.read_bytes". TPU runtime
	// distributions use "tpu_runtime.distributions" and generic metrics
	// "generic.value".
	Path string

	// Info describes the field: unit, title, kind, chart range. Synthesized
	// for TPU distributions and generic metrics, whose titles are data.
	Info *spb.MetricInfo

	// Accelerator is the device type for accelerator fields, including TPU
	// runtime distributions; ACCELERATOR_UNSPECIFIED otherwise.
	Accelerator spb.AcceleratorType

	// Vars identifies the measured thing: "index", "host", "path", "device",
	// "label", "name", "source", "series", "stat", and "labels" (the sorted
	// "key=value" pairs of a generic metric).
	Vars map[string]string

	// Value is in Info.Unit.
	Value float64
}

// Samples returns every measured value of a record with its schema
// information, in field order.
func Samples(rec *spb.SystemMetricsRecord) []Sample {
	if rec == nil {
		return nil
	}

	var samples []Sample
	walk(rec.ProtoReflect(), scope{}, "", func(l leaf) {
		samples = append(samples, Sample{
			Path:        l.path,
			Info:        sampleInfo(l),
			Accelerator: l.scope.accel,
			Vars:        l.scope.vars,
			Value:       l.value,
		})
	})

	for _, d := range rec.GetTpuRuntime().GetDistributions() {
		spec, ok := tpuDistributions[d.GetKind()]
		if !ok {
			continue
		}
		for i, value := range tpuDistributionStats(d) {
			if value == nil {
				continue
			}
			samples = append(samples, Sample{
				Path:        "tpu_runtime.distributions",
				Info:        &spb.MetricInfo{Display: spec.display, Unit: spec.canonicalUnit},
				Accelerator: spb.AcceleratorType_GOOGLE_TPU,
				Vars:        map[string]string{"label": d.GetLabel(), "stat": tpuStats[i]},
				Value:       *value,
			})
		}
	}

	return samples
}

// sampleInfo returns the MetricInfo for a leaf. A generic metric's title,
// unit and kind come from the producer, not from the schema.
func sampleInfo(l leaf) *spb.MetricInfo {
	if l.path != "generic.value" {
		return l.info
	}
	return &spb.MetricInfo{
		Display: l.scope.vars["name"],
		Unit:    l.scope.vars["unit"],
		Kind:    l.scope.kind,
	}
}

// labelPairs renders a generic metric's labels as sorted "key=value" pairs.
func labelPairs(labels protoreflect.List) string {
	pairs := make([]string, 0, labels.Len())
	for i := 0; i < labels.Len(); i++ {
		label := labels.Get(i).Message()
		fields := label.Descriptor().Fields()
		pairs = append(pairs,
			label.Get(fields.ByName("key")).String()+"="+label.Get(fields.ByName("value")).String())
	}
	sort.Strings(pairs)
	return strings.Join(pairs, " ")
}
