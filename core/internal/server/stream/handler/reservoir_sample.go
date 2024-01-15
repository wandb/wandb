package handler

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

func (r *ReservoirSampling[T]) Add(value T) {
	x := rand.Float64()
	if x < r.computeQ(r.j+1) {
		item := &Item[T]{value: value, priority: x, timestamp: r.j}
		heap.Push(&r.waitingList, item)
	}
	r.j += 1
}

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
