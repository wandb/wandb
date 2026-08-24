package leet

import (
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// testOverviewSidebar returns an expanded run overview sidebar with items
// in every section (2 environment, 1 config, 1 summary), along with its
// run overview for feeding in more data.
func testOverviewSidebar(t *testing.T, side SidebarSide, width int) (
	*RunOverview,
	*RunOverviewSidebar,
) {
	t.Helper()

	cfg := NewConfigManager(filepath.Join(t.TempDir(), "config.json"), nil)
	ro := NewRunOverview()
	sb := NewRunOverviewSidebar(cfg, NewAnimatedValue(true, width), ro, side)

	ro.ProcessRunMsg(RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"trainer", "epochs"}, ValueJson: "10"},
			},
		},
	})
	ro.ProcessSummaryMsg([]*spb.SummaryRecord{
		{Update: []*spb.SummaryItem{{NestedKey: []string{"acc"}, ValueJson: "0.9"}}},
	})
	ro.ProcessSystemInfoMsg(&spb.EnvironmentRecord{WriterId: "writer-1", Os: "linux"})
	sb.Sync()

	return ro, sb
}

func TestSectionWeights_DraggedFractions(t *testing.T) {
	_, sb := testOverviewSidebar(t, SidebarSideLeft, 40)

	// Without overrides, the built-in weights apply (normalized to sum 1).
	w := sb.sectionWeights([]int{3, 6, 4})
	require.InDelta(t, 0.20, w[0], 1e-9)
	require.InDelta(t, 0.35, w[1], 1e-9)
	require.InDelta(t, 0.45, w[2], 1e-9)

	// A dragged share is used as-is; unset sections keep their default
	// weights, so a section that appears later always gets a share.
	sb.overridesSource = func() LayoutOverrides {
		return LayoutOverrides{OverviewEnv: 0.3, OverviewConfig: 0.7}
	}
	w = sb.sectionWeights([]int{3, 6, 4})
	require.InDelta(t, 0.3, w[0], 1e-9)
	require.InDelta(t, 0.7, w[1], 1e-9)
	require.InDelta(t, 0.45, w[2], 1e-9)

	// Hidden sections get no weight.
	w = sb.sectionWeights([]int{0, 6, 4})
	require.Zero(t, w[0])
	require.InDelta(t, 0.7, w[1], 1e-9)
	require.InDelta(t, 0.45, w[2], 1e-9)
}

// A drag persists a share for every visible section; feeding them back
// through the allocator must reproduce the dragged heights exactly, so the
// separator tracks the mouse 1:1.
func TestFlexSectionHeights_HonorsDraggedFractions(t *testing.T) {
	_, sb := testOverviewSidebar(t, SidebarSideLeft, 40)
	sb.overridesSource = func() LayoutOverrides {
		return LayoutOverrides{
			OverviewEnv:     0.2,
			OverviewConfig:  0.3,
			OverviewSummary: 0.5,
		}
	}

	needs := []int{10, 20, 30}
	got := flexSectionHeights(20, sb.sectionWeights(needs), needs)
	require.Equal(t, []int{4, 6, 10}, got)
}

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
