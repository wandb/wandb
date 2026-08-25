package leet

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestFlexSectionHeights(t *testing.T) {
	equal := []float64{1, 1, 1}

	tests := []struct {
		name    string
		area    int
		weights []float64
		needs   []int
		want    []int
	}{
		{
			name:    "hidden sections get no rows",
			area:    10,
			weights: equal,
			needs:   []int{0, 0, 0},
			want:    []int{0, 0, 0},
		},
		{
			name:    "everything fits at need",
			area:    100,
			weights: []float64{1, 1.5, 2},
			needs:   []int{3, 6, 4},
			want:    []int{3, 6, 4},
		},
		{
			name:    "single section takes the whole area",
			area:    10,
			weights: equal,
			needs:   []int{100, 0, 0},
			want:    []int{10, 0, 0},
		},
		{
			name:    "contention splits by weight",
			area:    9,
			weights: []float64{1, 2},
			needs:   []int{100, 100},
			want:    []int{3, 6},
		},
		{
			name:    "capped section frees rows for the rest",
			area:    20,
			weights: []float64{1, 1, 2},
			needs:   []int{3, 100, 100},
			want:    []int{3, 6, 11},
		},
		{
			name:    "squeezed section floors at the minimum",
			area:    7,
			weights: []float64{1, 10},
			needs:   []int{50, 50},
			want:    []int{2, 5},
		},
		{
			name:    "minimums overflow a tiny area",
			area:    3,
			weights: equal,
			needs:   []int{5, 5, 5},
			want:    []int{2, 2, 2},
		},
		{
			name:    "leftover row goes to the earlier of tied remainders",
			area:    7,
			weights: []float64{1, 1},
			needs:   []int{50, 50},
			want:    []int{4, 3},
		},
		{
			name:    "zero weights split evenly",
			area:    6,
			weights: []float64{0, 0},
			needs:   []int{50, 50},
			want:    []int{3, 3},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := flexSectionHeights(tt.area, tt.weights, tt.needs)
			require.Equal(t, tt.want, got)
		})
	}
}
