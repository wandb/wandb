package sampler

import (
	"container/heap"
	"math"
	"math/rand"
	"sort"
)

// ReservoirSampler is a data structure that samples k items from a stream of items.
type ReservoirSampler[T comparable] struct {

	// pq is a priority queue of items in the reservoir
	pq PriorityQueue[T]

	// k is the upper bound on the number of items returned by the sampler
	// it also affects the probability of adding an item to the reservoir
	k int

	// delta is a parameter that controls the probability of adding an item
	// to the reservoir
	delta float64

	// seen is a counter for the number of items seen thus far
	seen int
}

func NewReservoirSampler[T comparable](k int, delta float64) *ReservoirSampler[T] {
	return &ReservoirSampler[T]{
		pq:    make(PriorityQueue[T], 0),
		k:     k,
		delta: delta,
		seen:  0,
	}
}

// Add adds a new item to the reservoir with the given value.
// The item is added to the reservoir with probability q.
func (rs *ReservoirSampler[T]) Add(value T) {
	seen := rs.seen + 1

	// hurestic to calculate q for the probability of adding an item to the reservoir
	gamma := -math.Log(rs.delta) / float64(seen)
	ratio := float64(rs.k) / float64(seen)
	q := math.Min(1, ratio+gamma+math.Sqrt(math.Pow(gamma, 2)+2*gamma*ratio))

	// generate a random priority for the current item
	x := rand.Float64()

	// add the item to the reservoir if its priority is less than q
	if x < q {
		item := &Item[T]{value: value, priority: x, index: rs.seen}
		heap.Push(&rs.pq, item)
	}

	// update the total number of items seen so far
	rs.seen = seen
}

// Returns up to k items from the reservoir as samples based on the priorities
// of the items. The items are returned in the order they were added to the
// reservoir.
func (r *ReservoirSampler[T]) Sample() []T {
	// number of items to return
	k := min(r.k, r.pq.Len())

	// pop k items from the priority queue
	topK := make([]*Item[T], k)
	for i := 0; i < k; i++ {
		topK[i] = heap.Pop(&r.pq).(*Item[T])
	}

	// sort the items by their index, so they are returned in the order they were added
	sort.Slice(topK, func(i, j int) bool {
		return topK[i].index < topK[j].index
	})

	// return only the values of the items as the samples
	samples := make([]T, k)
	for i, item := range topK {
		samples[i] = item.value
	}
	return samples
}
