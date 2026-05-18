package wbapi_test

import (
	"regexp"
	"strings"
	"testing"

	"github.com/wandb/wandb/core/internal/wbapi"
)

// normalize strips comments and collapses all whitespace runs so that test
// comparisons aren't sensitive to the formatter's exact indentation.
func normalize(t *testing.T, s string) string {
	t.Helper()
	// Drop everything from `#` to end of line (GraphQL line comments).
	s = regexp.MustCompile(`(?m)#.*$`).ReplaceAllString(s, "")
	// Insert spaces around punctuation so we can collapse whitespace cleanly.
	s = regexp.MustCompile(`[ \t]+`).ReplaceAllString(s, " ")
	s = regexp.MustCompile(`\s*\n\s*`).ReplaceAllString(s, "\n")
	s = strings.TrimSpace(s)
	return s
}

func mustRewrite(t *testing.T, query string, opts wbapi.GQLCompatOptions) string {
	t.Helper()
	got, err := opts.RewriteQuery(query)
	if err != nil {
		t.Fatalf("rewriteQuery: %v", err)
	}
	return got
}

func TestRewriteQuery_NoOptionsReturnsInputUnchanged(t *testing.T) {
	const q = "query Q { a b c }"
	got, err := wbapi.GQLCompatOptions{}.RewriteQuery(q)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != q {
		t.Errorf("expected unchanged input, got %q", got)
	}
}

func TestRewriteQuery_StripsVariablesFieldsAndFragments(t *testing.T) {
	const orig = `mutation updateArtifact(
		$artifactID: ID!
		$description: String
		$metadata: JSONString
		$ttlDurationSeconds: Int64
		$tagsToAdd: [TagInput!]
		$tagsToDelete: [TagInput!]
		$aliases: [ArtifactAliasInput!]
	) {
		updateArtifact(
			input: {
				artifactID: $artifactID,
				description: $description,
				metadata: $metadata,
				ttlDurationSeconds: $ttlDurationSeconds,
				tagsToAdd: $tagsToAdd,
				tagsToDelete: $tagsToDelete,
				aliases: $aliases
			}
		) {
			artifact {
				...ArtifactIdAndName
				...ArtifactInfo
				ttlDurationSeconds
				ttlIsInherited
				tags { name }
			}
		}
	}
	fragment ArtifactIdAndName on Artifact { id name }
	fragment ArtifactInfo on Artifact { description versionIndex }
	`

	got := mustRewrite(t, orig, wbapi.GQLCompatOptions{
		OmitVariables: map[string]bool{
			"ttlDurationSeconds": true,
			"tagsToAdd":          true,
			"tagsToDelete":       true,
		},
		OmitFragments: map[string]bool{"ArtifactInfo": true},
		OmitFields: map[string]bool{
			"ttlDurationSeconds": true,
			"ttlIsInherited":     true,
			"tags":               true,
		},
	})

	gotN := normalize(t, got)

	for _, banned := range []string{
		"ttlDurationSeconds",
		"tagsToAdd",
		"tagsToDelete",
		"ttlIsInherited",
		"ArtifactInfo",
	} {
		if strings.Contains(gotN, banned) {
			t.Errorf("rewritten query should not contain %q:\n%s", banned, gotN)
		}
	}
	for _, kept := range []string{
		"$artifactID:",
		"$aliases:",
		"ArtifactIdAndName",
		"fragment ArtifactIdAndName",
	} {
		if !strings.Contains(gotN, kept) {
			t.Errorf("rewritten query should contain %q:\n%s", kept, gotN)
		}
	}
}

func TestRewriteQuery_PrunesOrphanFragments(t *testing.T) {
	const orig = `fragment KeptFragmentA on KeptTypeA { keptInnerFieldA }
	query MyQuery {
		...KeptFragmentA
		...KeptFragmentB
		keptField
		removedParentField { ...RemovedFragment }
	}
	fragment RemovedFragment on RemovedType {
		removedInnerField
		...OrphanedFragment
	}
	fragment OrphanedFragment on RemovedType { anotherRemovedInnerField }
	fragment KeptFragmentB on KeptTypeB { ...KeptNestedFragment }
	fragment KeptNestedFragment on KeptTypeB { keptInnerFieldB }
	`

	checkPruned := func(t *testing.T, got string) {
		t.Helper()
		gotN := normalize(t, got)
		for _, banned := range []string{
			"RemovedFragment",
			"OrphanedFragment",
			"removedParentField",
		} {
			if strings.Contains(gotN, banned) {
				t.Errorf("should not contain %q:\n%s", banned, gotN)
			}
		}
		for _, kept := range []string{
			"KeptFragmentA",
			"KeptFragmentB",
			"KeptNestedFragment",
			"keptField",
		} {
			if !strings.Contains(gotN, kept) {
				t.Errorf("should contain %q:\n%s", kept, gotN)
			}
		}
	}

	t.Run("by fragment name", func(t *testing.T) {
		got := mustRewrite(t, orig, wbapi.GQLCompatOptions{
			OmitFragments: map[string]bool{"RemovedFragment": true},
		})
		checkPruned(t, got)
	})

	t.Run("by parent field name", func(t *testing.T) {
		got := mustRewrite(t, orig, wbapi.GQLCompatOptions{
			OmitFields: map[string]bool{"removedParentField": true},
		})
		checkPruned(t, got)
	})
}

func TestRewriteQuery_RenameFieldsPreservesAlias(t *testing.T) {
	const orig = `query ArtifactTypeArtifactCollections(
		$entityName: String!,
		$projectName: String!,
		$artifactTypeName: String!,
		$cursor: String
	) {
		project(name: $projectName, entityName: $entityName) {
			artifactType(name: $artifactTypeName) {
				artifactCollections: artifactCollections(after: $cursor) {
					pageInfo { endCursor hasNextPage }
					totalCount
				}
			}
		}
	}`

	got := mustRewrite(t, orig, wbapi.GQLCompatOptions{
		RenameFields: map[string]string{"artifactCollections": "artifactSequences"},
	})

	gotN := normalize(t, got)
	// The aliased call site should keep the alias and rename the underlying
	// field. We accept whatever exact spacing the formatter emits.
	if !strings.Contains(gotN, "artifactCollections: artifactSequences") {
		t.Errorf("missing alias-preserving rename:\n%s", gotN)
	}
	if strings.Contains(gotN, "artifactCollections(after:") {
		t.Errorf("unrenamed call survived:\n%s", gotN)
	}
}

func TestRewriteQuery_OmitOnlyTargetField(t *testing.T) {
	const orig = `query Q {
		project {
			artifactType {
				artifactCollections {
					pageInfo { endCursor }
					edges { node { id } }
					totalCount
				}
			}
		}
	}`

	got := mustRewrite(t, orig, wbapi.GQLCompatOptions{
		OmitFields: map[string]bool{"totalCount": true},
	})
	gotN := normalize(t, got)
	if strings.Contains(gotN, "totalCount") {
		t.Errorf("totalCount should be removed:\n%s", gotN)
	}
	if !strings.Contains(gotN, "pageInfo") {
		t.Errorf("siblings should be preserved:\n%s", gotN)
	}
	if !strings.Contains(gotN, "edges") {
		t.Errorf("siblings should be preserved:\n%s", gotN)
	}
}

func TestRewriteQuery_RewritesInlineFragments(t *testing.T) {
	const orig = `query Q {
		node {
			... on Artifact {
				keptField
				removedField
				...KeptFragment
			}
		}
	}
	fragment KeptFragment on Artifact { nestedKeptField }`

	got := mustRewrite(t, orig, wbapi.GQLCompatOptions{
		OmitFields: map[string]bool{"removedField": true},
	})
	gotN := normalize(t, got)

	for _, kept := range []string{
		"... on Artifact",
		"keptField",
		"KeptFragment",
		"fragment KeptFragment",
		"nestedKeptField",
	} {
		if !strings.Contains(gotN, kept) {
			t.Errorf("rewritten query should contain %q:\n%s", kept, gotN)
		}
	}
	if strings.Contains(gotN, "removedField") {
		t.Errorf("removedField should be removed:\n%s", gotN)
	}
}

func TestRewriteQuery_ParseFailureReturnsError(t *testing.T) {
	_, err := wbapi.GQLCompatOptions{
		OmitFields: map[string]bool{"x": true},
	}.RewriteQuery("not a graphql {")
	if err == nil {
		t.Fatal("expected parse error, got nil")
	}
}

func TestGQLCompatOptionsFromRequest(t *testing.T) {
	opts := wbapi.GQLCompatOptionsFromRequest(
		[]string{"varA"},
		[]string{"FragmentA"},
		[]string{"fieldA"},
		map[string]string{"oldField": "newField"},
	)

	if !opts.OmitVariables["varA"] {
		t.Error("expected varA to be omitted")
	}
	if !opts.OmitFragments["FragmentA"] {
		t.Error("expected FragmentA to be omitted")
	}
	if !opts.OmitFields["fieldA"] {
		t.Error("expected fieldA to be omitted")
	}
	if got := opts.RenameFields["oldField"]; got != "newField" {
		t.Errorf("expected oldField to rename to newField, got %q", got)
	}
}
