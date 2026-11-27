package metricsbatch

import (
	"math"
	"strconv"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
)

func TestBuilderEstimateAppendSize(t *testing.T) {
	b := NewBuilder()
	check := func(row *Row) {
		t.Helper()
		before := proto.Size(b.batch)
		predicted := b.EstimateAppendSize(row)
		require.Equal(t, before, proto.Size(b.batch))
		require.Equal(t, before, b.EncodedSize())
		b.Append(row)
		require.Equal(t, proto.Size(b.batch), predicted)
		require.Equal(t, predicted, b.EncodedSize())
	}

	check(&Row{})
	check(&Row{step: math.MinInt64, hasStep: true})
	check(&Row{cells: []cell{
		{key: "null", kind: filestreamv1.MetricsBatch_KIND_NULL},
		{key: "float", kind: filestreamv1.MetricsBatch_KIND_FLOAT, float: math.Inf(1)},
		{key: "int", kind: filestreamv1.MetricsBatch_KIND_INT, int: math.MaxInt64},
		{key: "bool", kind: filestreamv1.MetricsBatch_KIND_BOOL, bool: true},
		{key: "string", kind: filestreamv1.MetricsBatch_KIND_STRING, text: ""},
		{
			key:  strings.Repeat("k", 128),
			kind: filestreamv1.MetricsBatch_KIND_JSON,
			text: "[" + strings.Repeat("0,", 128) + "0]",
		},
	}})

	// Cross key-ID and row-end varint widths and packed lengths at 128
	// and 16384 bytes, with both new and repeated keys.
	wide := &Row{}
	for i := range 16385 {
		wide.cells = append(wide.cells, cell{
			key:  strconv.Itoa(i),
			kind: filestreamv1.MetricsBatch_KIND_NULL,
		})
	}
	check(&Row{cells: wide.cells[:121]})
	check(&Row{cells: wide.cells[121:122]})
	check(&Row{cells: wide.cells[122:8180]})
	check(&Row{cells: wide.cells[8180:]})
	check(&Row{cells: []cell{wide.cells[0], wide.cells[128], wide.cells[16384]}})

	finishedSize := b.EncodedSize()
	finished := b.Finish()
	check(&Row{cells: []cell{wide.cells[16384]}})
	require.Equal(t, finishedSize, proto.Size(finished))
}
