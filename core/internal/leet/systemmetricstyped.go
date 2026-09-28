package leet

import (
	"fmt"
	"strings"

	"github.com/wandb/wandb/core/internal/systemmetrics"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ProcessSamples ingests the samples of one typed system metrics record.
//
// Charts come from the schema: one per field (and per accelerator type), with
// the title, unit and range from the field's MetricInfo, and one series per
// measured device, core, disk, or label set.
func (g *SystemMetricsGrid) ProcessSamples(msg SystemMetricsMsg) {
	if len(msg.Samples) == 0 {
		return
	}

	chartSetChanged := false
	for _, sample := range msg.Samples {
		key := sampleChartKey(sample)
		def, ok := g.typedDefs[key]
		if !ok {
			def = metricDefForSample(sample)
			g.typedDefs[key] = def
		}

		chart, created := g.getOrCreateChart(key, def)
		chart.AddDataPoint(sampleSeriesName(sample), msg.Timestamp, sample.Value)
		if created {
			chartSetChanged = true
		}
	}
	if chartSetChanged {
		g.refreshChartSet()
	}
}

// sampleChartKey groups samples that belong on one chart: the same field of
// the same accelerator type, or the same generic metric of one source.
func sampleChartKey(s systemmetrics.Sample) string {
	key := "typed:" + s.Path
	if s.Accelerator != spb.AcceleratorType_ACCELERATOR_UNSPECIFIED {
		key += "|" + s.Accelerator.String()
	}
	switch s.Path {
	case "generic.value":
		key += "|" + s.Vars["source"] + "|" + s.Vars["name"]
	case "tpu_runtime.distributions":
		key += "|" + s.Info.GetDisplay()
	}
	return key
}

// metricDefForSample builds a chart definition from a sample's MetricInfo.
func metricDefForSample(s systemmetrics.Sample) *MetricDef {
	def := &MetricDef{
		Name:       sampleChartName(s),
		Unit:       unitFormatterFor(s.Info.GetUnit()),
		Percentage: s.Info.GetUnit() == "%",
		MinY:       0,
		MaxY:       100,
		AutoRange:  true,
	}
	if s.Info.RangeMin != nil && s.Info.RangeMax != nil {
		def.MinY, def.MaxY = s.Info.GetRangeMin(), s.Info.GetRangeMax()
		def.AutoRange = false
	}
	return def
}

// acceleratorNames titles accelerator charts and series.
var acceleratorNames = map[spb.AcceleratorType]string{
	spb.AcceleratorType_NVIDIA_GPU:   "GPU",
	spb.AcceleratorType_AMD_GPU:      "GPU",
	spb.AcceleratorType_APPLE_GPU:    "GPU",
	spb.AcceleratorType_APPLE_ANE:    "ANE",
	spb.AcceleratorType_GOOGLE_TPU:   "TPU",
	spb.AcceleratorType_AWS_TRAINIUM: "Trainium",
}

func sampleChartName(s systemmetrics.Sample) string {
	if name, ok := acceleratorNames[s.Accelerator]; ok {
		return name + " " + s.Info.GetDisplay()
	}
	return s.Info.GetDisplay()
}

// sampleSeriesName names the series a sample belongs to within its chart.
func sampleSeriesName(s systemmetrics.Sample) string {
	switch {
	case s.Path == "generic.value":
		if labels := s.Vars["labels"]; labels != "" {
			return labels
		}
	case s.Path == "tpu_runtime.distributions":
		return strings.TrimSpace(s.Vars["label"] + " " + s.Vars["stat"])
	case strings.HasPrefix(s.Path, "host.cpu.cores."):
		return "Core " + s.Vars["index"]
	case strings.HasPrefix(s.Path, "host.disk_usage."):
		return s.Vars["path"]
	case strings.HasPrefix(s.Path, "host.disk_io."):
		return s.Vars["device"]
	case s.Path == "tpu_runtime.hlo_queue_size.size":
		return s.Vars["label"]
	case s.Accelerator != spb.AcceleratorType_ACCELERATOR_UNSPECIFIED:
		name := fmt.Sprintf("%s %s", acceleratorNames[s.Accelerator], s.Vars["index"])
		if host := s.Vars["host"]; host != "" {
			return host + " " + name
		}
		return name
	}
	return DefaultSystemMetricSeriesName
}

// unitFormatterFor maps a schema (UCUM) unit to an axis formatter.
func unitFormatterFor(unit string) UnitFormatter {
	switch unit {
	case "", "1":
		return UnitScalar
	case "%":
		return UnitPercent
	case "By":
		return UnitBytes
	case "By/s":
		return UnitBps
	case "W":
		return UnitWatt
	case "Cel":
		return UnitCelsius
	case "MHz":
		return UnitMHz
	case "us":
		return UnitNamed("µs")
	default:
		return UnitNamed(unit)
	}
}
