package sampler_test

import (
	"math/rand/v2"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/sampler"
)

func getTestRandom() *rand.Rand {
	return rand.New(rand.NewPCG(1, 2))
}

func TestFewerThanKItems(t *testing.T) {
	sampler := sampler.NewReservoirSampler[int](getTestRandom(), 5)

	for i := range 5 {
		sampler.Add(i)
	}

	assert.Equal(t, []int{0, 1, 2, 3, 4}, sampler.Sample())
}

func TestSamplingLooksCorrect(t *testing.T) {
	sampler := sampler.NewReservoirSampler[int](getTestRandom(), 5)

	for i := range 100 {
		sampler.Add(i)
	}

	// A nice, random-looking sample, in the correct order.
	//
	// This test needs to be updated when the implementation changes.
	// Make sure the output is reasonable.
	assert.Equal(t, []int{14, 54, 58, 75, 97}, sampler.Sample())
}

func TestSamplesAreUniform(t *testing.T) {
	// Run a statistical test in addition to the at-a-glance test above.
	//
	// This is Pearson's chi-squared test. With 100,000 trials each drawing
	// a sample of 10 values from the range [0, 99], we expect each value to
	// occur in a sample about 10,000 times.

	rand := getTestRandom()
	freq := make([]int, 100)

	// Run trials and see how often each number is sampled.
	for range 100000 {
		sampler := sampler.NewReservoirSampler[int](rand, 10)
		for i := range 100 {
			sampler.Add(i)
		}
		for _, x := range sampler.Sample() {
			freq[x]++
		}
	}

	// Compute the test statistic, which follows the chi-squared distribution
	// with 99 degrees of freedom.
	statistic := 0.0
	for _, x := range freq {
		diff := float64(x-10000) / 100.0
		statistic += diff * diff
	}

	// If the sampler is working properly, there is about a 90% chance of this
	// being true. On the other hand, if the values are not very uniformly
	// distributed, this statistic will be large.
	assert.Less(t, statistic, 117.4)
}
