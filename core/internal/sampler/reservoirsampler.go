package sampler

import (
	"math"
	"math/rand/v2"
	"slices"
)

// ReservoirSampler implements reservoir sampling.
//
// Reservoir sampling is a technique to select a random sample of k items
// from a large population in a single pass, without storing the entire
// population in memory.
type ReservoirSampler[T comparable] struct {
	rand *rand.Rand

	// k is the size of the sample we are generating.
	k int

	// w is the 'w' parameter of Algorithm L.
	//
	// If we were to generate a random number in the range [0, 1] for each
	// item processed by the sampler, 'w' is the kth smallest so far.
	w float64

	// nextAccepted is the index of the next value that will land in the sample.
	nextAccepted int

	// sample is the current sample of up to k items.
	sample []reservoirItem[T]

	// seen is the number of items processed by the sampler so far.
	seen int
}

type reservoirItem[T comparable] struct {
	value         T
	originalIndex int
}

func NewReservoirSampler[T comparable](rand *rand.Rand, k int) *ReservoirSampler[T] {
	// NOTE: nextAccepted is initialized to the index of the next item after
	// the first k items that ends up in the sample. We only start to use it
	// after the first k items have been selected.
	skip, w := getSkipAndW(rand, 1, k)
	nextAccepted := k + skip

	return &ReservoirSampler[T]{
		rand:         rand,
		k:            k,
		w:            w,
		nextAccepted: nextAccepted,
		sample:       make([]reservoirItem[T], 0, k),
	}
}

// Add adds a new item to the reservoir with the given value.
func (rs *ReservoirSampler[T]) Add(value T) {
	index := rs.seen
	rs.seen++

	// Add the first k items directly to the sample.
	if index < rs.k {
		rs.sample = append(rs.sample, reservoirItem[T]{value, index})
		return
	}

	// Skip items until the next index that will land in the sample.
	//
	// This avoids generating random numbers unnecessarily.
	if index < rs.nextAccepted {
		return
	}

	// Replace a random item in the sample by the new item.
	rs.sample[rs.rand.IntN(len(rs.sample))] = reservoirItem[T]{value, index}

	skip, w := getSkipAndW(rs.rand, rs.w, rs.k)
	rs.w = w
	rs.nextAccepted = index + skip + 1
}

// Sample returns a sample of size k from the added items.
//
// Returned values are in the same order they were added.
func (rs *ReservoirSampler[T]) Sample() []T {
	// Sort the sampled items to appear in the order they were added.
	//
	// We do this when extracting the sample to avoid incurring a cost on
	// each addition to the sampler.
	slices.SortFunc(rs.sample, func(a, b reservoirItem[T]) int {
		return a.originalIndex - b.originalIndex
	})

	sample := make([]T, len(rs.sample))
	for i := range len(sample) {
		sample[i] = rs.sample[i].value
	}
	return sample
}

// getSkipAndW returns updated parameters of the sampling algorithm.
//
// The first return value is the number of items to skip until the next item
// that should be inserted into the sample.
//
// The second return value is the next 'w' parameter, which should be passed
// to the next call of this function. On the first call, it should be set to 1.
// The 'w' returned by the Nth call to this is a random number distributed
// as the kth smallest of (k + N - 1) independent random numbers selected
// uniformly from the range (0, 1).
//
// 'k' is the size of the sample we are generating.
func getSkipAndW(rand *rand.Rand, w float64, k int) (int, float64) {
	nextW := w * math.Exp(randLogFloat(rand)/float64(k))

	skip := int(randLogFloat(rand) / math.Log(1-nextW))

	if skip < 0 {
		// This can only happen on overflow. It just means that the current
		// sample is the final chosen sample.
		return math.MaxInt, nextW
	} else {
		return skip, nextW
	}
}

// randLogFloat returns the logarithm of a random number in the range (0, 1).
//
// The returned value is roughly in the range (-710, 0], since the logarithm
// of the smallest nonzero float64 is approximately -709.
func randLogFloat(rand *rand.Rand) float64 {
	x := rand.Float64()

	if x <= 0 {
		return math.Log(math.SmallestNonzeroFloat64)
	} else {
		return math.Log(x)
	}
}
