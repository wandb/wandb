package generate

// This file contains helpers to do various bits of validation in the process
// of converting types to Go, notably, for cases where we need to check that
// two types match.

import (
	"fmt"

	"github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/parser"
)

// selectionsMatch recursively compares the two selection-sets, and returns an
// error if they differ.
//
// It does not check arguments and directives, only field names, aliases,
// order, and fragment-structure.  It does not recurse into named fragments, it
// only checks that their names match.
//
// If both selection-sets are nil/empty, they compare equal.
func selectionsMatch(
	pos *ast.Position,
	expectedSelectionSet, actualSelectionSet ast.SelectionSet,
) error {
	if len(expectedSelectionSet) != len(actualSelectionSet) {
		return errorf(
			pos, "expected %d fields, got %d",
			len(expectedSelectionSet), len(actualSelectionSet))
	}

	for i, expected := range expectedSelectionSet {
		switch expected := expected.(type) {
		case *ast.Field:
			actual, ok := actualSelectionSet[i].(*ast.Field)
			switch {
			case !ok:
				return errorf(actual.Position,
					"expected selection #%d to be field, got %T",
					i, actualSelectionSet[i])
			case actual.Name != expected.Name:
				return errorf(actual.Position,
					"expected field %d to be %s, got %s",
					i, expected.Name, actual.Name)
			case actual.Alias != expected.Alias:
				return errorf(actual.Position,
					"expected field %d's alias to be %s, got %s",
					i, expected.Alias, actual.Alias)
			}
			err := selectionsMatch(actual.Position, expected.SelectionSet, actual.SelectionSet)
			if err != nil {
				return fmt.Errorf("in %s sub-selection: %w", actual.Alias, err)
			}
		case *ast.InlineFragment:
			actual, ok := actualSelectionSet[i].(*ast.InlineFragment)
			switch {
			case !ok:
				return errorf(actual.Position,
					"expected selection %d to be inline fragment, got %T",
					i, actualSelectionSet[i])
			case actual.TypeCondition != expected.TypeCondition:
				return errorf(actual.Position,
					"expected fragment %d to be on type %s, got %s",
					i, expected.TypeCondition, actual.TypeCondition)
			}
			err := selectionsMatch(actual.Position, expected.SelectionSet, actual.SelectionSet)
			if err != nil {
				return fmt.Errorf("in inline fragment on %s: %w", actual.TypeCondition, err)
			}
		case *ast.FragmentSpread:
			actual, ok := actualSelectionSet[i].(*ast.FragmentSpread)
			switch {
			case !ok:
				return errorf(actual.Position,
					"expected selection %d to be fragment spread, got %T",
					i, actualSelectionSet[i])
			case actual.Name != expected.Name:
				return errorf(actual.Position,
					"expected fragment %d to be ...%s, got ...%s",
					i, expected.Name, actual.Name)
			}
		}
	}
	return nil
}

// validateBindingSelection checks that if you requested in your type-binding
// that this type must always request certain fields, then in fact it does.
func (g *generator) validateBindingSelection(
	typeName string,
	binding *TypeBinding,
	pos *ast.Position,
	selectionSet ast.SelectionSet,
) error {
	if binding.ExpectExactFields == "" {
		return nil // no validation requested
	}

	// HACK: we parse the selection as if it were a query, which is basically
	// the same (for syntax purposes; it of course wouldn't validate)
	doc, gqlErr := parser.ParseQuery(&ast.Source{Input: binding.ExpectExactFields})
	if gqlErr != nil {
		return errorf(
			nil, "invalid type-binding %s.expect_exact_fields: %w", typeName, gqlErr)
	}

	err := selectionsMatch(pos, doc.Operations[0].SelectionSet, selectionSet)
	if err != nil {
		return fmt.Errorf("invalid selection for type-binding %s: %w", typeName, err)
	}
	return nil
}
