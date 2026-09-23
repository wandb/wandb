package leet_test

import (
	"fmt"
	"path/filepath"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

// projectRunsPage is a QueryProjectRuns response with runs given as
// {ID, display name, state}.
func projectRunsPage(hasNextPage bool, runs ...[3]string) string {
	edges := make([]string, 0, len(runs))
	for _, run := range runs {
		edges = append(edges, fmt.Sprintf(
			`{"node": {"name": %q, "displayName": %q, "state": %q}}`,
			run[0], run[1], run[2]))
	}
	return fmt.Sprintf(`{"project": {"runs": {
		"edges": [%s],
		"pageInfo": {"endCursor": "cursor", "hasNextPage": %t}
	}}}`, strings.Join(edges, ","), hasNextPage)
}

func TestRemoteWorkspace_ListsProjectRuns(t *testing.T) {
	logger := observability.NewNoOpLogger()
	first := [3]string{"run1", "first", "finished"}
	second := [3]string{"run2", "second", "running"}
	third := [3]string{"run3", "third", "running"}
	mockGQL := gqlmock.NewMockClient()
	projectRuns := gqlmock.WithOpName("QueryProjectRuns")
	mockGQL.StubMatchOnce(projectRuns, `{"project": null}`)
	mockGQL.StubMatchOnce(projectRuns, projectRunsPage(true, second))
	// A run created while paging repeats the previous page's last run.
	mockGQL.StubMatchOnce(projectRuns, projectRunsPage(false, second, first))
	mockGQL.StubMatchOnce(projectRuns, projectRunsPage(false,
		third, [3]string{"run2", "second", "finished"}, first))

	backend := leet.TestRemoteWorkspaceBackend("entity", "project", mockGQL, logger)
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := leet.NewWorkspace(backend, cfg, logger)
	w.Update(tea.WindowSizeMsg{Width: 120, Height: 30})
	discover := func() string {
		w.Update(backend.DiscoverRunsCmd(0)())
		return stripANSI(w.View().Content)
	}

	assert.Contains(t, discover(), "Error: project entity/project not found")
	discover()
	view := discover()
	assert.NotContains(t, view, "Error")
	assert.Contains(t, view, "State: Running")
	assert.Equal(t, []string{"run2", "run1"}, w.TestFilteredRunKeys())

	view = discover()
	assert.Contains(t, view, "third")
	assert.Contains(t, view, "State: Finished")
	assert.Equal(t, []string{"run3", "run2", "run1"}, w.TestFilteredRunKeys())
}

func TestModel_EscFromRemoteRunOpensProjectWorkspace(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	backend := leet.TestRemoteWorkspaceBackend("entity", "project", gqlmock.NewMockClient(), logger)
	var model tea.Model = leet.NewModel(leet.ModelParams{
		Backend: backend,
		RunParams: &leet.RunParams{Remote: &leet.RemoteRunParams{
			Entity: "entity", Project: "project", RunID: "run1",
		}},
		Config: cfg,
		Logger: logger,
	})
	model, _ = model.Update(tea.WindowSizeMsg{Width: 120, Height: 30})

	model, _ = model.Update(tea.KeyPressMsg{Code: tea.KeyEscape})

	assert.Contains(t, stripANSI(model.View().Content), "Runs")
}
