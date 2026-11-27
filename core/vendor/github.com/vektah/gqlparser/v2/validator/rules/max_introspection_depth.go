package rules

import (
	"github.com/vektah/gqlparser/v2/ast"
	//nolint:staticcheck // Validator rules each use dot imports for convenience.
	. "github.com/vektah/gqlparser/v2/validator/core"
)

const maxListsDepth = 3

// MaxIntrospectionDepth reports an introspection selection that nests __Type's list
// fields past a fixed depth.
//
// A fragment cycle whose lap gains depth nests past any limit, so the rule reports it
// without needing NoFragmentCyclesRule to run alongside. A cycle whose lap gains none
// reaches no new depth and is cut, as it is in graphql-js.
var MaxIntrospectionDepth = Rule{
	Name: "MaxIntrospectionDepth",
	RuleFunc: func(observers *Events, addError AddErrFunc) {
		// One checker per document: a fragment's result at a given depth is the same
		// whichever introspection root reached it, so a document with many roots that
		// spread the same fragments checks each of them once rather than once per root.
		c := &depthChecker{
			visitedFragments: make(map[string]int),
			memo:             make(map[fragmentAtDepth]bool),
		}

		// Counts the depth of list fields in "__Type" recursively and
		// returns `true` if the limit has been reached.
		observers.OnField(func(walker *Walker, field *ast.Field) {
			if field.Name == "__schema" || field.Name == "__type" {
				if c.checkDepthField(field, 0) {
					addError(
						Message(`Maximum introspection depth exceeded`),
						At(field.Position),
					)
				}
				return
			}
		})
	},
}

type fragmentAtDepth struct {
	name  string
	depth int
}

// depthChecker walks a document's introspection fields, reusing each fragment's result
// rather than following every path to it.
//
// A fragment's result depends on the depth it is entered at and on which fragments are
// already being visited, since one that is still being visited is answered from its entry
// depth rather than by walking it. Only a cycle reaches a fragment that is still being
// visited, so for an acyclic document the entry depth alone identifies the result and the
// memo is exact.
//
// On a cyclic document a fragment memoized under such an answer can be reused by an
// introspection root that would have walked it, leaving the violation reported on fewer
// roots than an uncached walk reports it on. Never on none: the walk that answered from
// the entry depth is the one that goes on to find the violation. That trade is worth
// making, because only a cycle reaches an in-progress fragment, so no valid document loses
// anything, while every document gains the memo.
//
// graphql-js does not memoize here and pays the exponential walk, so this is a deliberate
// divergence from the reference implementation.
type depthChecker struct {
	// visitedFragments holds the depth at which each in-progress fragment was entered.
	visitedFragments map[string]int
	// memo keeps the walk linear: without it, a fragment spread twice in each of n nested
	// fragments is walked 2^n times.
	memo map[fragmentAtDepth]bool
}

func (c *depthChecker) checkDepthSelectionSet(selectionSet ast.SelectionSet, depth int) bool {
	for _, child := range selectionSet {
		if field, ok := child.(*ast.Field); ok {
			if c.checkDepthField(field, depth) {
				return true
			}
		}
		if fragmentSpread, ok := child.(*ast.FragmentSpread); ok {
			if c.checkDepthFragmentSpread(fragmentSpread, depth) {
				return true
			}
		}
		if inlineFragment, ok := child.(*ast.InlineFragment); ok {
			if c.checkDepthSelectionSet(inlineFragment.SelectionSet, depth) {
				return true
			}
		}
	}
	return false
}

func (c *depthChecker) checkDepthField(field *ast.Field, depth int) bool {
	if field.Name == "fields" ||
		field.Name == "interfaces" ||
		field.Name == "possibleTypes" ||
		field.Name == "inputFields" {
		depth++
		if depth >= maxListsDepth {
			return true
		}
	}
	return c.checkDepthSelectionSet(field.SelectionSet, depth)
}

func (c *depthChecker) checkDepthFragmentSpread(
	fragmentSpread *ast.FragmentSpread,
	depth int,
) bool {
	fragmentName := fragmentSpread.Name
	if entryDepth, visiting := c.visitedFragments[fragmentName]; visiting {
		// A cycle. Depth only grows, so if the walk gained any on the way round it gains
		// that much again on every further lap and the selection nests past any limit. A
		// lap that gained none reaches nothing the walk already in progress will not.
		return depth > entryDepth
	}
	fragment := fragmentSpread.Definition
	if fragment == nil {
		// Missing fragments checks are handled by `KnownFragmentNamesRule`.
		return false
	}

	key := fragmentAtDepth{fragmentName, depth}
	if exceeded, ok := c.memo[key]; ok {
		return exceeded
	}

	// Rather than following an immutable programming pattern which has
	// significant memory and garbage collection overhead, we've opted to
	// take a mutable approach for efficiency's sake. Importantly visiting a
	// fragment twice is fine, so long as you don't do one visit inside the
	// other.
	c.visitedFragments[fragmentName] = depth
	defer delete(c.visitedFragments, fragmentName)

	exceeded := c.checkDepthSelectionSet(fragment.SelectionSet, depth)
	c.memo[key] = exceeded
	return exceeded
}
