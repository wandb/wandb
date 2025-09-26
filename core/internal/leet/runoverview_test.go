package leet_test

import (
	"strings"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	leet "github.com/wandb/wandb/core/internal/leet"
)

func TestSidebarFilter_WithPrefixes(t *testing.T) {
	s := leet.NewSidebar(leet.GetConfig())
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

func TestSidebar_SelectsFirstNonEmptySection(t *testing.T) {
	s := leet.NewSidebar(leet.GetConfig())
	s.SetRunOverview(leet.RunOverview{
		// Only config is non-empty.
		Config:      map[string]any{"trainer": map[string]any{"epochs": 10}},
		Summary:     map[string]any{},
		Environment: map[string]any{},
	})

	key, val := s.GetSelectedItem()
	if key != "trainer.epochs" || val != "10" {
		t.Fatalf("selected item = {%q,%q}; want {\"trainer.epochs\",\"10\"}", key, val)
	}
}

func TestSidebar_ConfirmSummaryFilterSelectsSummary(t *testing.T) {
	s := leet.NewSidebar(leet.GetConfig())
	s.SetRunOverview(leet.RunOverview{
		Config: map[string]any{"trainer": map[string]any{"epochs": 10}},
		Summary: map[string]any{
			"acc":  0.9,
			"loss": 0.5,
		},
	})

	// Live preview on summary, then apply it.
	s.StartFilter()
	s.UpdateFilter("@s acc")
	s.ConfirmFilter()

	key, _ := s.GetSelectedItem()
	if key != "acc" {
		t.Fatalf("after summary filter, selected key=%q; want \"acc\"", key)
	}
}

func expandSidebar(t *testing.T, s *leet.Sidebar, termWidth int, rightVisible bool) {
	t.Helper()
	s.UpdateDimensions(termWidth, rightVisible)
	s.Toggle()
	time.Sleep(leet.AnimationDuration + 20*time.Millisecond)
	// Drive animation to completion.
	s.Update(leet.SidebarAnimationMsg{})
}

func TestSidebar_CalculateSectionHeights_PaginationAndAllItems(t *testing.T) {
	s := leet.NewSidebar(leet.GetConfig())
	expandSidebar(t, s, 120, false)

	ro := leet.RunOverview{
		Config: map[string]any{
			"alpha": map[string]any{"a": 1, "b": 2, "c": 3},
			"beta":  map[string]any{"d": 4, "e": 5},
		}, // 5 items
		Summary:     map[string]any{"acc": 0.91, "val": map[string]any{"acc": 0.88}},                           // 2 items
		Environment: map[string]any{"writer-1": map[string]any{"os": "linux", "cpu": "x86_64", "ram": "64GB"}}, // 3 items
	}
	s.SetRunOverview(ro)

	// Small height -> ItemsPerPage=1 -> expect "[1-1 of N]" pagination per section.
	view := s.View(15)
	if !strings.Contains(view, "Config") || !strings.Contains(view, "Summary") || !strings.Contains(view, "Environment") {
		t.Fatalf("expected all section headers in view; got:\n%s", view)
	}
	if !strings.Contains(view, "Config [1-1 of 5]") {
		t.Fatalf("expected paginated config header; got:\n%s", view)
	}
	if !strings.Contains(view, "Summary [1-1 of 2]") {
		t.Fatalf("expected paginated summary header; got:\n%s", view)
	}

	// Larger height -> enough space -> expect "[N items]" (non-paginated).
	view = s.View(40)
	if !strings.Contains(view, "Config [5 items]") || !strings.Contains(view, "Summary [2 items]") {
		t.Fatalf("expected non-paginated headers with item counts; got:\n%s", view)
	}

	s.Toggle()
}

func TestSidebar_Navigation_SectionPageUpDown(t *testing.T) {
	s := leet.NewSidebar(leet.GetConfig())
	expandSidebar(t, s, 120, false)
	s.SetRunOverview(leet.RunOverview{
		Config: map[string]any{
			"alpha": map[string]any{"a": 1, "z": 2},
			"beta":  map[string]any{"b": 3},
		},
		Summary:     map[string]any{"acc": 0.9, "loss": 0.1},
		Environment: map[string]any{"writer-1": map[string]any{"os": "linux", "cpu": "x86"}},
	})

	// Start in Environment; Tab to Config (navigateSection).
	s.Update(tea.KeyMsg{Type: tea.KeyTab})
	key, _ := s.GetSelectedItem()
	if !strings.HasPrefix(key, "alpha.") && !strings.HasPrefix(key, "beta.") {
		t.Fatalf("expected to be in Config after Tab, got key=%q", key)
	}

	// Height=15 -> 1 item/page; Down moves to next page/next item (navigateDown + navigatePage).
	_ = s.View(15)
	s.Update(tea.KeyMsg{Type: tea.KeyDown})
	key2, _ := s.GetSelectedItem()
	if key2 == key {
		t.Fatalf("expected selection to move with Down; still at %q", key2)
	}

	// Page right, then left, then Up; remain in Config.
	s.Update(tea.KeyMsg{Type: tea.KeyRight})
	s.Update(tea.KeyMsg{Type: tea.KeyLeft})
	s.Update(tea.KeyMsg{Type: tea.KeyUp})
	key3, _ := s.GetSelectedItem()
	if !strings.HasPrefix(key3, "alpha.") && !strings.HasPrefix(key3, "beta.") {
		t.Fatalf("expected to stay in Config after paging; got key=%q", key3)
	}

	// Shift-Tab back to previous section (Environment).
	s.Update(tea.KeyMsg{Type: tea.KeyShiftTab})
	key4, _ := s.GetSelectedItem()
	if strings.HasPrefix(key4, "alpha.") || strings.HasPrefix(key4, "beta.") {
		t.Fatalf("expected to be back in Environment; got key=%q", key4)
	}
}

func TestSidebar_ClearFilter_PublicPath(t *testing.T) {
	s := leet.NewSidebar(leet.GetConfig())
	expandSidebar(t, s, 120, false)
	s.SetRunOverview(leet.RunOverview{
		Config:      map[string]any{"alpha": map[string]any{"a": 1, "b": 2}},
		Summary:     map[string]any{"acc": 0.91},
		Environment: map[string]any{"writer-1": map[string]any{"os": "linux"}},
	})

	// Apply a filter and verify info shows.
	s.StartFilter()
	s.UpdateFilter("acc")
	s.ConfirmFilter()
	if info := s.GetFilterInfo(); info == "" {
		t.Fatal("expected filter info after applying filter")
	}

	// Clearing via an empty confirmed query hides the info and restores all items.
	s.StartFilter()
	s.UpdateFilter("")
	s.ConfirmFilter()
	if info := s.GetFilterInfo(); info != "" {
		t.Fatalf("expected empty filter info after clearing; got %q", info)
	}
	if view := s.View(40); !strings.Contains(view, "Config [2 items]") {
		t.Fatalf("expected full config section after clearing filter; got:\n%s", view)
	}
}

func TestSidebar_TruncateValue(t *testing.T) {
	s := leet.NewSidebar(leet.GetConfig())
	expandSidebar(t, s, 40, false) // clamps to SidebarMinWidth

	long := strings.Repeat("x", 200)
	s.SetRunOverview(leet.RunOverview{
		Config:      map[string]any{"a": map[string]any{"k": long}},
		Summary:     map[string]any{},
		Environment: map[string]any{"writer-1": map[string]any{"os": "linux"}},
	})

	view := s.View(12)
	if !strings.Contains(view, "a.k") || !strings.Contains(view, "...") {
		t.Fatalf("expected truncated value in view; got:\n%s", view)
	}
}
