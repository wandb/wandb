package runhistory_test

import (
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
)

func TestRunHistorySampler(t *testing.T) {
	sampler := runhistory.NewRunHistorySampler()

	row1 := runhistory.New()
	row1.SetFloat(pathtree.PathOf("a"), 1.1)
	row1.SetFloat(pathtree.PathOf("x", "y"), 1.2) // nested keys are ignored

	row2 := runhistory.New()
	row2.SetString(pathtree.PathOf("a"), "test") // non-numbers are ignored
	row2.SetFloat(pathtree.PathOf("b"), 8)

	row3 := runhistory.New()
	row3.SetInt(pathtree.PathOf("a"), 2)

	sampler.SampleNext(row1)
	sampler.SampleNext(row2)
	sampler.SampleNext(row3)

	// Get() iterates a map, so it does not return the items in a
	// guaranteed order. Index by key to make the assertion order-independent.
	valuesByKey := make(map[string][]float32)
	for _, item := range sampler.Get() {
		valuesByKey[item.Key] = item.ValuesFloat
	}

	// The reservoir holds up to 48 values per metric, so all the values
	// in this test are kept.
	assert.Equal(t,
		map[string][]float32{
			"a": {1.1, 2},
			"b": {8},
		},
		valuesByKey)
}
