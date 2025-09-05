package leet_test

import (
	"testing"

	leet "github.com/wandb/wandb/core/internal/leet"
)

func TestSidebarFilter_WithPrefixes(t *testing.T) {
	t.Parallel()
	s := leet.NewSidebar()
	s.SetRunOverview(leet.RunOverview{
		Config:      map[string]any{"trainer": map[string]any{"epochs": 10}},
		Summary:     map[string]any{"acc": 0.9},
		Environment: map[string]any{"writer-1": map[string]any{"os": "linux"}},
	})
	s.StartFilter()
	s.UpdateFilter("@c train") // live preview
	if info := s.GetFilterInfo(); info == "" {
		t.Fatal("expected filter info for config section")
	}
	s.ConfirmFilter() // locks it in
}
