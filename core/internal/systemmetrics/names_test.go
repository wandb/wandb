package systemmetrics_test

import (
	"regexp"
	"testing"

	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// A semantic-conventions namespace or a vendor's reverse domain.
var metricName = regexp.MustCompile(
	`^((hw|system|process)|com\.(nvidia|google|amazon|amd|apple|coreweave))(\.[a-z0-9_]+)+$`)

// TestMetricNames checks that every measured field has a well-formed
// OpenTelemetry name.
func TestMetricNames(t *testing.T) {
	check := func(where string, info *spb.MetricInfo) {
		assert.NotEmpty(t, info.GetNames(), where)
		for _, name := range info.GetNames() {
			assert.Regexp(t, metricName, name.GetName(), where)
		}
	}

	seen := map[protoreflect.FullName]bool{}
	var walk func(protoreflect.MessageDescriptor)
	walk = func(md protoreflect.MessageDescriptor) {
		if seen[md.FullName()] {
			return
		}
		seen[md.FullName()] = true
		for i := range md.Fields().Len() {
			fd := md.Fields().Get(i)
			if fd.Message() != nil {
				walk(fd.Message())
			}
			opts := fd.Options()
			if proto.HasExtension(opts, spb.E_Metric) && md.Name() != "GenericMetric" {
				check(
					string(fd.FullName()),
					proto.GetExtension(opts, spb.E_Metric).(*spb.MetricInfo),
				)
			}
		}
	}
	walk((&spb.SystemMetricsRecord{}).ProtoReflect().Descriptor())

	kinds := spb.TpuRuntimeMetrics_DISTRIBUTION_UNSPECIFIED.Descriptor().Values()
	for i := 1; i < kinds.Len(); i++ {
		v := kinds.Get(i)
		check(
			string(v.FullName()),
			proto.GetExtension(v.Options(), spb.E_Distribution).(*spb.MetricInfo),
		)
	}
}
