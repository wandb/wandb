package leet

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func testRunFilterData() workspaceRunFilterData {
	return workspaceRunFilterData{
		RunKey:      "run-20260209_010101-abc123",
		DisplayName: "resnet50-baseline",
		ID:          "abc123",
		Project:     "vision",
		ConfigByPath: map[string]string{
			"lr":           "0.001",
			"optimizer":    "adamw",
			"model.layers": "12",
		},
		ConfigEntries: []runFilterConfigEntry{
			{Path: "lr", Value: "0.001"},
			{Path: "optimizer", Value: "adamw"},
			{Path: "model.layers", Value: "12"},
		},
	}
}

func TestCompileRunFilterQuery_BareTermMatchesIdentityFields(t *testing.T) {
	data := testRunFilterData()

	require.True(t, compileRunFilterQuery("vision", FilterModeRegex).Match(data))
	require.True(t, compileRunFilterQuery("resnet", FilterModeRegex).Match(data))
	require.True(t, compileRunFilterQuery("abc123", FilterModeRegex).Match(data))
	require.False(t, compileRunFilterQuery("nonexistent", FilterModeRegex).Match(data))
}

func TestCompileRunFilterQuery_ProjectAndConfigClauses(t *testing.T) {
	data := testRunFilterData()

	query := compileRunFilterQuery(
		"project:vision cfg.lr>=1e-3 cfg.optimizer=adamw cfg.model.layers=12",
		FilterModeRegex,
	)
	require.True(t, query.Match(data))

	query = compileRunFilterQuery("project:vision cfg.lr>0.01", FilterModeRegex)
	require.False(t, query.Match(data))
}

func TestCompileRunFilterQuery_GlobNegationAndOr(t *testing.T) {
	data := testRunFilterData()

	query := compileRunFilterQuery("project:vis* -name:debug | project:nlp", FilterModeGlob)
	require.True(t, query.Match(data))

	data.DisplayName = "debug-run"
	require.False(t, query.Match(data), "negated name clause should exclude the vision run")

	data.Project = "nlp"
	require.True(t, query.Match(data), "OR group should match the nlp project")
}

func TestCompileRunFilterQuery_HasAndConfigAnySearch(t *testing.T) {
	data := testRunFilterData()

	query := compileRunFilterQuery("has:cfg.lr config:adam", FilterModeRegex)
	require.True(t, query.Match(data))

	query = compileRunFilterQuery("has:cfg.missing", FilterModeRegex)
	require.False(t, query.Match(data))
}

func TestCompileRunFilterQuery_TextualBooleanAliases(t *testing.T) {
	data := testRunFilterData()

	query := compileRunFilterQuery(
		"project:vision AND NOT name:debug OR project:nlp", FilterModeRegex)
	require.True(t, query.Match(data))

	data.DisplayName = "debug-run"
	require.False(t, query.Match(data), "NOT alias should negate the following clause")
}
