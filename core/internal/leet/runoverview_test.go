package leet_test

import (
	"slices"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestRunOverview_ProcessRunMsg_StoresMetadataAndFlattensConfigSorted(t *testing.T) {
	ro := leet.NewRunOverview()

	// Intentionally provide keys out of order to verify flattening + stable sort.
	ro.ProcessRunMsg(leet.RunMsg{
		ID:          "run-42",
		DisplayName: "cool-run",
		Project:     "proj",
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"trainer", "lr"}, ValueJson: "0.01"},
				{NestedKey: []string{"alpha", "a"}, ValueJson: "1"},
				{NestedKey: []string{"trainer", "epochs"}, ValueJson: "10"},
			},
		},
	})

	require.Equal(t, "run-42", ro.ID())
	require.Equal(t, "cool-run", ro.DisplayName())
	require.Equal(t, "proj", ro.Project())

	items := ro.ConfigItems()
	require.Len(t, items, 3)

	require.Equal(t, "alpha.a", items[0].Key)
	require.Equal(t, "trainer.epochs", items[1].Key)
	require.Equal(t, "trainer.lr", items[2].Key)

	require.Equal(t, []string{"alpha", "a"}, items[0].Path)
	require.Equal(t, []string{"trainer", "epochs"}, items[1].Path)
	require.Equal(t, []string{"trainer", "lr"}, items[2].Path)

	require.Equal(t, "1", items[0].Value)
	require.Equal(t, "10", items[1].Value)
	require.Equal(t, "0.01", items[2].Value)
}

func TestRunOverview_ProcessSystemInfoMsg_YieldsEnvironmentItems(t *testing.T) {
	ro := leet.NewRunOverview()
	// First message creates the environment model and processes data.
	ro.ProcessSystemInfoMsg(&spb.EnvironmentRecord{
		WriterId: "writer-1",
		Os:       "linux",
	})

	env := ro.EnvironmentItems()
	require.NotEmpty(t, env, "expected at least one environment item")

	found := slices.ContainsFunc(env, func(kv leet.KeyValuePair) bool {
		return strings.Contains(strings.ToLower(kv.Value), "linux")
	})
	require.True(t, found, "expected an environment item containing 'linux'")
}

func TestRunOverview_ProcessSummaryMsg_FlattensAndSorts(t *testing.T) {
	ro := leet.NewRunOverview()

	s := &spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{NestedKey: []string{"val", "acc"}, ValueJson: "0.88"},
			{NestedKey: []string{"acc"}, ValueJson: "0.9"},
		},
	}
	ro.ProcessSummaryMsg([]*spb.SummaryRecord{s})

	items := ro.SummaryItems()
	require.Len(t, items, 2)
	require.Equal(t, "acc", items[0].Key)     // alphabetical before "val.acc"
	require.Equal(t, "val.acc", items[1].Key) // flattened nested key
	require.Equal(t, "0.9", items[0].Value)
	require.Equal(t, "0.88", items[1].Value)
}

func TestRunOverview_StateTransitions(t *testing.T) {
	ro := leet.NewRunOverview()
	require.Equal(t, leet.RunStateUnknown, ro.State())
	ro.ProcessRunMsg(leet.RunMsg{})
	require.Equal(t, leet.RunStateRunning, ro.State())

	ro.SetRunState(leet.RunStateFinished)
	require.Equal(t, leet.RunStateFinished, ro.State())
}

func TestRunOverview_Config_ListOfMaps_Flattens(t *testing.T) {
	ro := leet.NewRunOverview()
	ro.ProcessRunMsg(leet.RunMsg{
		Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{
				{NestedKey: []string{"a"}, ValueJson: `[{"b":1},{"c":2}]`},
			},
		},
	})

	items := ro.ConfigItems()
	require.Len(t, items, 2)
	require.Equal(t, "a[0].b", items[0].Key)
	require.Equal(t, "1", items[0].Value)
	require.Equal(t, []string{"a", "[0]", "b"}, items[0].Path)

	require.Equal(t, "a[1].c", items[1].Key)
	require.Equal(t, "2", items[1].Value)
	require.Equal(t, []string{"a", "[1]", "c"}, items[1].Path)
}
