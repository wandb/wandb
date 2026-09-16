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

	result := sampler.Get()
	assert.Len(t, result, 2)
	assert.Equal(t, "a", result[0].Key)
	assert.Equal(t, []float32{1.1, 2}, result[0].ValuesFloat)
	assert.Equal(t, "b", result[1].Key)
	assert.Equal(t, []float32{8}, result[1].ValuesFloat)
}
