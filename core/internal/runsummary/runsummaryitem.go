package runsummary

import (
	"golang.org/x/exp/constraints"
)

type Number interface {
	constraints.Integer | constraints.Float
}

type Aggregation int8

// supported aggregation types
const (
	Last Aggregation = iota
	Min
	Max
	Mean
	None
)

type Item[T Number] struct {
	Count  int
	Sum    T
	Min    T
	Max    T
	Mean   float64
	Latest interface{}
}

// NewItem creates a new summary item.
func NewItem[T Number]() *Item[T] {
	return &Item[T]{}
}

// Update updates the summary item with the given value.
func Update[T Number](i *Item[T], value T) {
	i.Latest = value
	i.Count++
	i.Sum += value
	if i.Count == 1 {
		i.Min = value
		i.Max = value
		i.Mean = float64(value)
		return
	}

	if value < i.Min {
		i.Min = value
	}
	if value > i.Max {
		i.Max = value
	}
	i.Mean = float64(i.Sum) / float64(i.Count)
}
