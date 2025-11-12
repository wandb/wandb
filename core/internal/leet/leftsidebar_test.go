package leet_test

import (
	"path/filepath"
	"strings"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"
	leet "github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestSidebarFilter_WithPrefixes(t *testing.T) {
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	s := leet.NewLeftSidebar(cfg)

	s.ProcessRunMsg(leet.RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"trainer", "epochs"}, ValueJson: "10"},
			},
		},
	})

	sr := &spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"acc"}, ValueJson: "0.9"},
		},
	}
	s.ProcessSummaryMsg([]*spb.SummaryRecord{sr})

	s.ProcessSystemInfoMsg(&spb.EnvironmentRecord{
		WriterId: "writer-1",
		Os:       "linux",
	})

	s.StartFilter()
	s.UpdateFilter("@c train") // live preview
	require.NotEmpty(t, s.FilterInfo())
	s.ConfirmFilter() // locks it in
}

func TestSidebar_SelectsFirstNonEmptySection(t *testing.T) {
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	s := leet.NewLeftSidebar(cfg)

	s.ProcessRunMsg(leet.RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"trainer", "epochs"}, ValueJson: "10"},
			},
		},
	})

	key, val := s.SelectedItem()
	require.Equal(t, key, "trainer.epochs")
	require.Equal(t, val, "10")
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

	sr := &spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"acc"}, ValueJson: "0.9"},
			{NestedKey: []string{"loss"}, ValueJson: "0.5"},
		},
	}
	s.ProcessSummaryMsg([]*spb.SummaryRecord{sr})

	// Live preview on summary, then apply it.
	s.StartFilter()
	s.UpdateFilter("@s acc")
	s.ConfirmFilter()

	key, _ := s.SelectedItem()
	require.Equal(t, key, "acc")
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
	_, _ = cfg.SetLeftSidebarVisible(false), cfg.SetRightSidebarVisible(false)
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

	sr := &spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"acc"}, ValueJson: "0.91"},
			{NestedKey: []string{"val", "acc"}, ValueJson: "0.88"},
		},
	}
	s.ProcessSummaryMsg([]*spb.SummaryRecord{sr})

	s.ProcessSystemInfoMsg(&spb.EnvironmentRecord{
		WriterId: "writer-1",
		Os:       "linux",
	})

	// Small height -> ItemsPerPage=1 -> expect "[1-1 of N]" pagination per section.
	view := s.View(15)
	require.Contains(t, view, "Config [1-2 of 5]")
	require.Contains(t, view, "Summary [1-1 of 2]")
	require.Contains(t, view, "Environment")

	// Larger height -> enough space -> expect "[N items]" (non-paginated).
	view = s.View(40)
	require.Contains(t, view, "Config [5 items]")
	require.Contains(t, view, "Summary [2 items]")

	s.Toggle()
}

func TestSidebar_Navigation_SectionPageUpDown(t *testing.T) {
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	_, _ = cfg.SetLeftSidebarVisible(false), cfg.SetRightSidebarVisible(false)
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

	sr := &spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"acc"}, ValueJson: "0.9"},
			{NestedKey: []string{"loss"}, ValueJson: "0.1"},
		},
	}
	s.ProcessSummaryMsg([]*spb.SummaryRecord{sr})

	// Start in Environment; Tab to Config (navigateSection).
	s.Update(tea.KeyMsg{Type: tea.KeyTab})
	key, _ := s.SelectedItem()
	require.True(t, strings.HasPrefix(key, "alpha.") || strings.HasPrefix(key, "beta."))

	// Height=15 -> 1 item/page; Down moves to next page/next item (navigateDown + navigatePage).
	_ = s.View(15)
	s.Update(tea.KeyMsg{Type: tea.KeyDown})
	key2, _ := s.SelectedItem()
	require.NotEqual(t, key2, key)

	// Page right, then left, then Up; remain in Config.
	s.Update(tea.KeyMsg{Type: tea.KeyRight})
	s.Update(tea.KeyMsg{Type: tea.KeyLeft})
	s.Update(tea.KeyMsg{Type: tea.KeyUp})
	key3, _ := s.SelectedItem()
	require.True(t, strings.HasPrefix(key3, "alpha.") || strings.HasPrefix(key3, "beta."))

	// Shift-Tab back to previous section (Environment).
	s.Update(tea.KeyMsg{Type: tea.KeyShiftTab})
	key4, _ := s.SelectedItem()
	require.False(t, strings.HasPrefix(key4, "alpha.") || strings.HasPrefix(key4, "beta."))
}

func TestSidebar_ClearFilter_PublicPath(t *testing.T) {
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	_, _ = cfg.SetLeftSidebarVisible(false), cfg.SetRightSidebarVisible(false)
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

	sr := &spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"acc"}, ValueJson: "0.91"},
		},
	}
	s.ProcessSummaryMsg([]*spb.SummaryRecord{sr})

	s.ProcessSystemInfoMsg(&spb.EnvironmentRecord{
		WriterId: "writer-1",
		Os:       "linux",
	})

	// Apply a filter and verify info shows.
	s.StartFilter()
	s.UpdateFilter("acc")
	s.ConfirmFilter()
	require.NotEmpty(t, s.FilterInfo())

	// Clearing via an empty confirmed query hides the info and restores all items.
	s.StartFilter()
	s.UpdateFilter("")
	s.ConfirmFilter()
	require.Empty(t, s.FilterInfo())
	view := s.View(40)
	require.Contains(t, view, "Config [2 items]")
}

func TestSidebar_TruncateValue(t *testing.T) {
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), observability.NewNoOpLogger())
	_, _ = cfg.SetLeftSidebarVisible(false), cfg.SetRightSidebarVisible(false)
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
	require.Contains(t, view, "a.k")
	require.Contains(t, view, "...")
}
