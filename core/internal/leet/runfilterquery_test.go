package leet_test

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func testRunFilterData() leet.WorkspaceRunFilterData {
	return leet.WorkspaceRunFilterData{
		RunKey:      "run-20260209_010101-abc123",
		DisplayName: "resnet50-baseline",
		ID:          "abc123",
		Project:     "vision",
		Notes:       "warm start from imagenet checkpoint",
		Tags:        []string{"scheduled", "release"},
		ConfigByPath: map[string]string{
			"lr":           "0.001",
			"optimizer":    "adamw",
			"model.layers": "12",
		},
		ConfigEntries: []leet.RunFilterConfigEntry{
			{Path: "lr", Value: "0.001"},
			{Path: "optimizer", Value: "adamw"},
			{Path: "model.layers", Value: "12"},
		},
	}
}

func TestCompileRunFilterQuery_BareTermMatchesIdentityFields(t *testing.T) {
	data := testRunFilterData()

	require.True(t, leet.CompileRunFilterQuery("vision", leet.FilterModeRegex).Match(data))
	require.True(t, leet.CompileRunFilterQuery("resnet", leet.FilterModeRegex).Match(data))
	require.True(t, leet.CompileRunFilterQuery("abc123", leet.FilterModeRegex).Match(data))
	require.True(t, leet.CompileRunFilterQuery("checkpoint", leet.FilterModeRegex).Match(data))
	require.True(t, leet.CompileRunFilterQuery("scheduled", leet.FilterModeRegex).Match(data))
	require.False(t, leet.CompileRunFilterQuery("nonexistent", leet.FilterModeRegex).Match(data))
}

func TestCompileRunFilterQuery_ProjectAndConfigClauses(t *testing.T) {
	data := testRunFilterData()

	query := leet.CompileRunFilterQuery(
		"project:vision cfg.lr>=1e-3 cfg.optimizer=adamw cfg.model.layers=12",
		leet.FilterModeRegex,
	)
	require.True(t, query.Match(data))

	query = leet.CompileRunFilterQuery("project:vision cfg.lr>0.01", leet.FilterModeRegex)
	require.False(t, query.Match(data))
}

func TestCompileRunFilterQuery_GlobNegationAndOr(t *testing.T) {
	data := testRunFilterData()

	query := leet.CompileRunFilterQuery(
		"project:vis* -name:debug | project:nlp", leet.FilterModeGlob)
	require.True(t, query.Match(data))

	data.DisplayName = "debug-run"
	require.False(t, query.Match(data), "negated name clause should exclude the vision run")

	data.Project = "nlp"
	require.True(t, query.Match(data), "OR group should match the nlp project")
}

func TestCompileRunFilterQuery_HasAndConfigAnySearch(t *testing.T) {
	data := testRunFilterData()

	query := leet.CompileRunFilterQuery("has:cfg.lr config:adam", leet.FilterModeRegex)
	require.True(t, query.Match(data))

	query = leet.CompileRunFilterQuery("has:cfg.missing", leet.FilterModeRegex)
	require.False(t, query.Match(data))
}

func TestCompileRunFilterQuery_TextualBooleanAliases(t *testing.T) {
	data := testRunFilterData()

	query := leet.CompileRunFilterQuery(
		"project:vision AND NOT name:debug OR project:nlp", leet.FilterModeRegex)
	require.True(t, query.Match(data))

	data.DisplayName = "debug-run"
	require.False(t, query.Match(data), "NOT alias should negate the following clause")
}

func TestCompileRunFilterQuery_ExactMatchDoesNotCoerceNumericLookingIDs(t *testing.T) {
	data := testRunFilterData()
	data.ID = "00123"
	data.Project = "010"

	require.True(t, leet.CompileRunFilterQuery("id=00123", leet.FilterModeRegex).Match(data))
	require.False(t, leet.CompileRunFilterQuery("id=123", leet.FilterModeRegex).Match(data))

	require.True(t, leet.CompileRunFilterQuery("project=010", leet.FilterModeRegex).Match(data))
	require.False(t, leet.CompileRunFilterQuery("project=10", leet.FilterModeRegex).Match(data))
}

func TestCompileRunFilterQuery_QuotedTermsAndEscapes(t *testing.T) {
	data := testRunFilterData()
	data.DisplayName = `exp "alpha" baseline`

	require.True(t,
		leet.CompileRunFilterQuery(`name:"exp \"alpha\""`, leet.FilterModeRegex).Match(data))
	require.False(t,
		leet.CompileRunFilterQuery(`name:"exp \"beta\""`, leet.FilterModeRegex).Match(data))
}

func TestCompileRunFilterQuery_DisplayAliasesAreConsistentAcrossOperators(t *testing.T) {
	data := leet.WorkspaceRunFilterData{
		RunKey:      "run-20260209_010101-vision01",
		DisplayName: "baseline",
	}

	for _, query := range []string{
		"run_name:base",
		"name:base",
		"display:base",
		"display_name:base",

		"run_name=baseline",
		"name=baseline",
		"display=baseline",
		"display_name=baseline",

		"run_name!=other",
		"name!=other",
		"display!=other",
		"display_name!=other",

		"has:run_name",
		"has:name",
		"has:display",
		"has:display_name",
	} {
		require.Truef(
			t,
			leet.CompileRunFilterQuery(query, leet.FilterModeRegex).Match(data),
			"query=%q",
			query,
		)
	}
}

func TestCompileRunFilterQuery_TagAndNoteAliasesAreConsistentAcrossOperators(t *testing.T) {
	data := testRunFilterData()

	for _, query := range []string{
		"tag:scheduled",
		"tags:scheduled",
		"tag=release",
		"tags=release",
		"tag!=canary",
		"tags!=canary",
		"has:tag",
		"has:tags",

		"note:checkpoint",
		"notes:checkpoint",
		`note="warm start from imagenet checkpoint"`,
		`notes="warm start from imagenet checkpoint"`,
		"note!=debug",
		"notes!=debug",
		"has:note",
		"has:notes",
	} {
		require.Truef(
			t,
			leet.CompileRunFilterQuery(query, leet.FilterModeRegex).Match(data),
			"query=%q",
			query,
		)
	}

	require.False(t, leet.CompileRunFilterQuery("tag!=release", leet.FilterModeRegex).Match(data))
	require.False(t, leet.CompileRunFilterQuery("note:ablation", leet.FilterModeRegex).Match(data))
}
