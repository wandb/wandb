package runhistory_test

import (
	"testing"

	"github.com/stretchr/testify/assert"

	. "github.com/wandb/wandb/core/internal/runhistory"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestRunHistorySampler(t *testing.T) {
	sampler := NewRunHistorySampler()
	data := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			// Should go to the same key.
			{NestedKey: []string{"a"}, ValueJson: "1.1"},
			{Key: "a", ValueJson: "2.2"},
			{Key: "a", ValueJson: "3"},

			// Should ignore empty keys and nested metrics.
			{ValueJson: "13"},
			{NestedKey: []string{"a", "b"}, ValueJson: "14"},

			// Should ignore non-numeric values.
			{Key: "b", ValueJson: `"5"`},
			{Key: "b", ValueJson: "6"},
		},
	}

	sampler.SampleNext(data)

	result := sampler.Get()
	assert.Len(t, result, 2)
	assert.Equal(t, "a", result[0].Key)
	assert.Equal(t, []float32{1.1, 2.2, 3}, result[0].ValuesFloat)
	assert.Equal(t, "b", result[1].Key)
	assert.Equal(t, []float32{6}, result[1].ValuesFloat)
}
