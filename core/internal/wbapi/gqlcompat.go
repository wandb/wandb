package wbapi

import (
	"bytes"
	"fmt"

	"github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/formatter"
	"github.com/vektah/gqlparser/v2/parser"
)

// gqlCompatOptions are the rewrites applied to a GraphQL document before it
// is forwarded to the upstream W&B backend. They let the client strip parts
// of a generated query that the deployed server version does not support,
// without reproducing a GraphQL parser in Python.
type gqlCompatOptions struct {
	OmitVariables map[string]bool
	OmitFragments map[string]bool
	OmitFields    map[string]bool
	RenameFields  map[string]string
}

func (o gqlCompatOptions) empty() bool {
	return len(o.OmitVariables) == 0 &&
		len(o.OmitFragments) == 0 &&
		len(o.OmitFields) == 0 &&
		len(o.RenameFields) == 0
}

// rewriteQuery applies the configured rewrites and returns the rewritten
// document. If no rewrites are configured the original query is returned
// unchanged (no parse / format round-trip).
func rewriteQuery(query string, opts gqlCompatOptions) (string, error) {
	if opts.empty() {
		return query, nil
	}

	doc, err := parser.ParseQuery(&ast.Source{Name: "compat", Input: query})
	if err != nil {
		return "", fmt.Errorf("gqlcompat: parse: %w", err)
	}

	// Drop fragment definitions targeted by OmitFragments. Removing them
	// before walking selection sets keeps `pruneOrphanFragments` work small.
	if len(opts.OmitFragments) > 0 {
		doc.Fragments = filterFragments(doc.Fragments, opts.OmitFragments)
	}

	for _, op := range doc.Operations {
		if len(opts.OmitVariables) > 0 {
			op.VariableDefinitions = filterVariableDefinitions(
				op.VariableDefinitions, opts.OmitVariables,
			)
		}
		op.SelectionSet = rewriteSelectionSet(op.SelectionSet, opts)
	}

	for _, frag := range doc.Fragments {
		frag.SelectionSet = rewriteSelectionSet(frag.SelectionSet, opts)
	}

	doc.Fragments = pruneOrphanFragments(doc)

	var buf bytes.Buffer
	formatter.NewFormatter(&buf).FormatQueryDocument(doc)
	return buf.String(), nil
}

func filterFragments(
	frags ast.FragmentDefinitionList,
	omit map[string]bool,
) ast.FragmentDefinitionList {
	kept := frags[:0]
	for _, f := range frags {
		if !omit[f.Name] {
			kept = append(kept, f)
		}
	}
	return kept
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
// selection set in the source but is empty after rewriting is dropped — this
// matches the Python behavior of pruning `parent { ...RemovedFragment }` to
// nothing.
func rewriteSelectionSet(
	sel ast.SelectionSet,
	opts gqlCompatOptions,
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
			hadSelections := len(s.SelectionSet) > 0
			if hadSelections {
				s.SelectionSet = rewriteSelectionSet(s.SelectionSet, opts)
				if len(s.SelectionSet) == 0 {
					continue
				}
			}
			out = append(out, s)
		case *ast.FragmentSpread:
			if opts.OmitFragments[s.Name] {
				continue
			}
			out = append(out, s)
		case *ast.InlineFragment:
			s.SelectionSet = rewriteSelectionSet(s.SelectionSet, opts)
			if len(s.SelectionSet) == 0 {
				continue
			}
			out = append(out, s)
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

// pruneOrphanFragments returns the subset of doc.Fragments transitively
// reachable from doc.Operations.
func pruneOrphanFragments(doc *ast.QueryDocument) ast.FragmentDefinitionList {
	if len(doc.Fragments) == 0 {
		return doc.Fragments
	}

	byName := make(map[string]*ast.FragmentDefinition, len(doc.Fragments))
	for _, f := range doc.Fragments {
		byName[f.Name] = f
	}

	used := make(map[string]bool, len(doc.Fragments))
	var visit func(ast.SelectionSet)
	visit = func(sel ast.SelectionSet) {
		for _, s := range sel {
			switch s := s.(type) {
			case *ast.Field:
				visit(s.SelectionSet)
			case *ast.FragmentSpread:
				if used[s.Name] {
					continue
				}
				used[s.Name] = true
				if frag := byName[s.Name]; frag != nil {
					visit(frag.SelectionSet)
				}
			case *ast.InlineFragment:
				visit(s.SelectionSet)
			}
		}
	}
	for _, op := range doc.Operations {
		visit(op.SelectionSet)
	}

	kept := doc.Fragments[:0]
	for _, f := range doc.Fragments {
		if used[f.Name] {
			kept = append(kept, f)
		}
	}
	return kept
}

// gqlCompatOptionsFromRequest builds rewrite options from a GraphQLRequest
// proto's omit_*/rename_fields fields.
func gqlCompatOptionsFromRequest(
	omitVariables, omitFragments, omitFields []string,
	renameFields map[string]string,
) gqlCompatOptions {
	return gqlCompatOptions{
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
