package wbapi

import (
	"bytes"
	"fmt"

	"github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/formatter"
	"github.com/vektah/gqlparser/v2/parser"
)

// GQLCompatOptions are the rewrites applied to a GraphQL document before it
// is forwarded to the upstream W&B backend. They let the client strip parts
// of a generated query that the deployed server version does not support.
type GQLCompatOptions struct {
	OmitVariables map[string]bool
	OmitFragments map[string]bool
	OmitFields    map[string]bool
	RenameFields  map[string]string
}

func (o GQLCompatOptions) empty() bool {
	return len(o.OmitVariables) == 0 &&
		len(o.OmitFragments) == 0 &&
		len(o.OmitFields) == 0 &&
		len(o.RenameFields) == 0
}

// RewriteQuery applies the configured rewrites and returns the rewritten
// document.
func (opts GQLCompatOptions) RewriteQuery(query string) (string, error) {
	if opts.empty() {
		return query, nil
	}

	doc, err := parser.ParseQuery(&ast.Source{
		Name:  "wandb-core GraphQL rewrite for older W&B server compatibility",
		Input: query,
	})
	if err != nil {
		return "", fmt.Errorf(
			"gqlcompat: rewrite GraphQL for older W&B server compatibility: parse: %w",
			err,
		)
	}

	for _, op := range doc.Operations {
		if len(opts.OmitVariables) > 0 {
			op.VariableDefinitions = filterVariableDefinitions(
				op.VariableDefinitions, opts.OmitVariables,
			)
		}
		op.SelectionSet = opts.rewriteSelectionSet(op.SelectionSet)
	}

	keptFragments := doc.Fragments[:0]
	for _, frag := range doc.Fragments {
		if opts.OmitFragments[frag.Name] {
			continue
		}
		frag.SelectionSet = opts.rewriteSelectionSet(frag.SelectionSet)
		keptFragments = append(keptFragments, frag)
	}
	doc.Fragments = keptFragments

	pruneOrphanFragments(doc)

	var buf bytes.Buffer
	formatter.NewFormatter(&buf).FormatQueryDocument(doc)
	return buf.String(), nil
}

func filterVariableDefinitions(
	defs ast.VariableDefinitionList,
	omit map[string]bool,
) ast.VariableDefinitionList {
	kept := defs[:0]
	for _, def := range defs {
		if !omit[def.Variable] {
			kept = append(kept, def)
		}
	}
	return kept
}

// rewriteSelectionSet applies the configured rewrites recursively.
//
// A field whose name matches OmitFields is dropped. A field whose name is in
// RenameFields is renamed (aliases are preserved). Arguments that resolve to
// an omitted variable are dropped, including those nested in input objects.
// Fragment spreads in OmitFragments are dropped. A field that had a non-empty
// selection set in the source but is empty after rewriting is dropped.
func (opts GQLCompatOptions) rewriteSelectionSet(
	sel ast.SelectionSet,
) ast.SelectionSet {
	out := sel[:0]
	for _, s := range sel {
		switch s := s.(type) {
		case *ast.Field:
			if opts.OmitFields[s.Name] {
				continue
			}

			if newName, ok := opts.RenameFields[s.Name]; ok {
				s.Name = newName
			}

			if len(opts.OmitVariables) > 0 {
				s.Arguments = filterArguments(s.Arguments, opts.OmitVariables)
			}

			// No subselection and field not omitted.
			if len(s.SelectionSet) == 0 {
				out = append(out, s)
				continue
			}

			// Rewrite the subselection. If this removes everything,
			// discard the field too.
			s.SelectionSet = opts.rewriteSelectionSet(s.SelectionSet)
			if len(s.SelectionSet) > 0 {
				out = append(out, s)
			}

		case *ast.FragmentSpread:
			if opts.OmitFragments[s.Name] {
				continue
			}
			out = append(out, s)

		case *ast.InlineFragment:
			s.SelectionSet = opts.rewriteSelectionSet(s.SelectionSet)
			if len(s.SelectionSet) > 0 {
				out = append(out, s)
			}

		default:
			out = append(out, s)
		}
	}
	return out
}

// filterArguments removes top-level arguments whose value is an omitted
// variable, and strips object fields nested inside input objects whose value
// is an omitted variable.
func filterArguments(
	args ast.ArgumentList,
	omitVars map[string]bool,
) ast.ArgumentList {
	kept := args[:0]
	for _, arg := range args {
		if valueIsOmittedVariable(arg.Value, omitVars) {
			continue
		}
		stripOmittedVarsFromValue(arg.Value, omitVars)
		kept = append(kept, arg)
	}
	return kept
}

func valueIsOmittedVariable(v *ast.Value, omitVars map[string]bool) bool {
	return v != nil && v.Kind == ast.Variable && omitVars[v.Raw]
}

// stripOmittedVarsFromValue mutates input-object values to remove fields whose
// value is an omitted variable. List values are left alone — positional list
// items don't have field names, and dropping them would change semantics.
func stripOmittedVarsFromValue(v *ast.Value, omitVars map[string]bool) {
	if v == nil || v.Kind != ast.ObjectValue {
		return
	}
	kept := v.Children[:0]
	for _, c := range v.Children {
		if valueIsOmittedVariable(c.Value, omitVars) {
			continue
		}
		stripOmittedVarsFromValue(c.Value, omitVars)
		kept = append(kept, c)
	}
	v.Children = kept
}

// pruneOrphanFragments removes fragment definitions that are not transitively
// reachable from doc.Operations.
func pruneOrphanFragments(doc *ast.QueryDocument) {
	if len(doc.Fragments) == 0 {
		return
	}

	byName := make(map[string]*ast.FragmentDefinition, len(doc.Fragments))
	for _, f := range doc.Fragments {
		byName[f.Name] = f
	}

	used := make(map[string]bool, len(doc.Fragments))
	for _, op := range doc.Operations {
		markUsedFragments(op.SelectionSet, byName, used)
	}

	kept := doc.Fragments[:0]
	for _, f := range doc.Fragments {
		if used[f.Name] {
			kept = append(kept, f)
		}
	}
	doc.Fragments = kept
}

func markUsedFragments(
	sel ast.SelectionSet,
	byName map[string]*ast.FragmentDefinition,
	used map[string]bool,
) {
	for _, s := range sel {
		switch s := s.(type) {
		case *ast.Field:
			markUsedFragments(s.SelectionSet, byName, used)

		case *ast.FragmentSpread:
			if used[s.Name] {
				continue
			}
			used[s.Name] = true
			if frag := byName[s.Name]; frag != nil {
				markUsedFragments(frag.SelectionSet, byName, used)
			}

		case *ast.InlineFragment:
			markUsedFragments(s.SelectionSet, byName, used)
		}
	}
}

// GQLCompatOptionsFromRequest builds rewrite options from a GraphQLRequest
// proto's omit_*/rename_fields fields.
func GQLCompatOptionsFromRequest(
	omitVariables, omitFragments, omitFields []string,
	renameFields map[string]string,
) GQLCompatOptions {
	return GQLCompatOptions{
		OmitVariables: stringSet(omitVariables),
		OmitFragments: stringSet(omitFragments),
		OmitFields:    stringSet(omitFields),
		RenameFields:  renameFields,
	}
}

func stringSet(values []string) map[string]bool {
	if len(values) == 0 {
		return nil
	}
	out := make(map[string]bool, len(values))
	for _, v := range values {
		out[v] = true
	}
	return out
}
