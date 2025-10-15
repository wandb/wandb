package leet_test

import (
	"path/filepath"
	"strings"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	leet "github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestSidebarFilter_WithPrefixes(t *testing.T) {
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	s := leet.NewLeftSidebar(cfg)

	// Use the actual ProcessRunMsg API with minimal proto
	s.ProcessRunMsg(leet.RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"trainer", "epochs"}, ValueJson: "10"},
			},
		},
	})

	s.ProcessSummaryMsg(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"acc"}, ValueJson: "0.9"},
		},
	})

	s.ProcessSystemInfoMsg(&spb.EnvironmentRecord{
		WriterId: "writer-1",
		Os:       "linux",
	})

	s.StartFilter()
	s.UpdateFilter("@c train") // live preview
	if info := s.GetFilterInfo(); info == "" {
		t.Fatal("expected filter info for config section")
	}
	s.ConfirmFilter() // locks it in
}

func TestSidebar_SelectsFirstNonEmptySection(t *testing.T) {
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	s := leet.NewLeftSidebar(cfg)

	// Only config is non-empty
	s.ProcessRunMsg(leet.RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"trainer", "epochs"}, ValueJson: "10"},
			},
		},
	})

	key, val := s.GetSelectedItem()
	if key != "trainer.epochs" || val != "10" {
		t.Fatalf("selected item = {%q,%q}; want {\"trainer.epochs\",\"10\"}", key, val)
	}
}

func TestSidebar_ConfirmSummaryFilterSelectsSummary(t *testing.T) {
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	s := leet.NewLeftSidebar(cfg)

	s.ProcessRunMsg(leet.RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"trainer", "epochs"}, ValueJson: "10"},
			},
		},
	})

	s.ProcessSummaryMsg(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"acc"}, ValueJson: "0.9"},
			{NestedKey: []string{"loss"}, ValueJson: "0.5"},
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

func expandSidebar(t *testing.T, s *leet.LeftSidebar, termWidth int, rightVisible bool) {
	t.Helper()
	s.UpdateDimensions(termWidth, rightVisible)
	s.Toggle()
	time.Sleep(leet.AnimationDuration + 20*time.Millisecond)
	// Drive animation to completion.
	s.Update(leet.LeftSidebarAnimationMsg{})
}

func TestSidebar_CalculateSectionHeights_PaginationAndAllItems(t *testing.T) {
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	s := leet.NewLeftSidebar(cfg)
	expandSidebar(t, s, 120, false)

	s.ProcessRunMsg(leet.RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"alpha", "a"}, ValueJson: "1"},
				{NestedKey: []string{"alpha", "b"}, ValueJson: "2"},
				{NestedKey: []string{"alpha", "c"}, ValueJson: "3"},
				{NestedKey: []string{"beta", "d"}, ValueJson: "4"},
				{NestedKey: []string{"beta", "e"}, ValueJson: "5"},
			},
		},
	})

	s.ProcessSummaryMsg(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"acc"}, ValueJson: "0.91"},
			{NestedKey: []string{"val", "acc"}, ValueJson: "0.88"},
		},
	})

	s.ProcessSystemInfoMsg(&spb.EnvironmentRecord{
		WriterId: "writer-1",
		Os:       "linux",
	})

	// Small height -> ItemsPerPage=1 -> expect "[1-1 of N]" pagination per section.
	view := s.View(15)
	if !strings.Contains(view, "Config") || !strings.Contains(view, "Summary") || !strings.Contains(view, "Environment") {
		t.Fatalf("expected all section headers in view; got:\n%s", view)
	}
	if !strings.Contains(view, "Config [1-2 of 5]") {
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
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	s := leet.NewLeftSidebar(cfg)
	expandSidebar(t, s, 120, false)

	s.ProcessSystemInfoMsg(&spb.EnvironmentRecord{
		WriterId: "writer-1",
		Os:       "linux",
	})

	s.ProcessRunMsg(leet.RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"alpha", "a"}, ValueJson: "1"},
				{NestedKey: []string{"alpha", "z"}, ValueJson: "2"},
				{NestedKey: []string{"beta", "b"}, ValueJson: "3"},
			},
		},
	})

	s.ProcessSummaryMsg(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"acc"}, ValueJson: "0.9"},
			{NestedKey: []string{"loss"}, ValueJson: "0.1"},
		},
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
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	s := leet.NewLeftSidebar(cfg)
	expandSidebar(t, s, 120, false)

	s.ProcessRunMsg(leet.RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"alpha", "a"}, ValueJson: "1"},
				{NestedKey: []string{"alpha", "b"}, ValueJson: "2"},
			},
		},
	})

	s.ProcessSummaryMsg(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"acc"}, ValueJson: "0.91"},
		},
	})

	s.ProcessSystemInfoMsg(&spb.EnvironmentRecord{
		WriterId: "writer-1",
		Os:       "linux",
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
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	s := leet.NewLeftSidebar(cfg)
	expandSidebar(t, s, 40, false) // clamps to SidebarMinWidth

	long := strings.Repeat("x", 200)

	s.ProcessRunMsg(leet.RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"a", "k"}, ValueJson: `"` + long + `"`},
			},
		},
	})

	s.ProcessSystemInfoMsg(&spb.EnvironmentRecord{
		WriterId: "writer-1",
		Os:       "linux",
	})

	view := s.View(12)
	if !strings.Contains(view, "a.k") || !strings.Contains(view, "...") {
		t.Fatalf("expected truncated value in view; got:\n%s", view)
	}
}
