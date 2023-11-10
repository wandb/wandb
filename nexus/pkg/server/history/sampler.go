package history

import (
	"container/heap"
	"fmt"
	"math"
	"math/rand"
	"sort"
)

type Item[T comparable] struct {
	value     T
	priority  float64
	timestamp int
}

func (item Item[T]) String() string {
	return fmt.Sprintf("%v", item.value)
}

// PriorityQueue implements heap.Interface and holds Items.
type PriorityQueue[T comparable] []*Item[T]

func (pq PriorityQueue[T]) Len() int           { return len(pq) }
func (pq PriorityQueue[T]) Less(i, j int) bool { return pq[i].priority < pq[j].priority }
func (pq PriorityQueue[T]) Swap(i, j int)      { pq[i], pq[j] = pq[j], pq[i] }

func (pq *PriorityQueue[T]) Push(x interface{}) {
	item := x.(*Item[T])
	*pq = append(*pq, item)
}

func (pq *PriorityQueue[T]) Pop() interface{} {
	old := *pq
	n := len(old)
	item := old[n-1]
	*pq = old[0 : n-1]
	return item
}

// ReservoirSampling implements reservoir sampling algorithm.
type ReservoirSampling[T comparable] struct {
	waitingList PriorityQueue[T]
	k           int
	delta       float64
	j           int
}

func (r *ReservoirSampling[T]) computeQ(j int) float64 {
	gamma := -math.Log(r.delta) / float64(j)
	ratio := float64(r.k) / float64(j)
	return math.Min(1, ratio+gamma+math.Sqrt(math.Pow(gamma, 2)+2*gamma*ratio))
}

// Add adds a new value to the reservoir.
func (r *ReservoirSampling[T]) Add(value T) {
	x := rand.Float64()
	if x < r.computeQ(r.j+1) {
		item := &Item[T]{value: value, priority: x, timestamp: r.j}
		heap.Push(&r.waitingList, item)
	}
	r.j += 1
}

// GetSample returns a sample of the reservoir.
func (r *ReservoirSampling[T]) GetSample() []T {
	k := min(r.k, r.waitingList.Len())
	result := make([]*Item[T], k)

	for i := 0; i < k; i++ {
		item := heap.Pop(&r.waitingList).(*Item[T])
		result[i] = item
	}
	sort.Slice(result, func(i, j int) bool {
		return result[i].timestamp < result[j].timestamp
	})

	values := make([]T, k)
	for i := 0; i < k; i++ {
		values[i] = result[i].value
	}

	return values
}

// SampleManager manages multiple reservoir samplers.
type SampleManager[T comparable] struct {
	samplers map[string]*ReservoirSampling[T]
	k        int
	delta    float64
}

// NewSampleManager creates a new SampleManager.
func NewSampleManager[T comparable](k int, delta float64) *SampleManager[T] {
	return &SampleManager[T]{
		k:     k,
		delta: delta,
	}
}

// Add adds a new value to the reservoir.
func (sm *SampleManager[T]) Add(key string, value T) {
	if sm.samplers == nil {
		sm.samplers = make(map[string]*ReservoirSampling[T])
	}

	if _, ok := sm.samplers[key]; !ok {
		sm.samplers[key] = &ReservoirSampling[T]{
			k:     sm.k,
			delta: sm.delta,
		}
	}
	sm.samplers[key].Add(value)
}

// Samples returns a map of samples.
func (sm *SampleManager[T]) Samples() map[string][]T {
	if sm.samplers == nil {
		return nil
	}
	samples := make(map[string][]T)
	for key, sampler := range sm.samplers {
		values := sampler.GetSample()
		samples[key] = values
	}
	return samples
}
