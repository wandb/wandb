package validator

import (
	"github.com/vektah/gqlparser/v2/ast"

	//nolint:revive // Validator rules each use dot imports for convenience.
	. "github.com/vektah/gqlparser/v2/validator"
)

func init() {
	AddRule("KnownFragmentNames", func(observers *Events, addError AddErrFunc) {
		observers.OnFragmentSpread(func(walker *Walker, fragmentSpread *ast.FragmentSpread) {
			if fragmentSpread.Definition == nil {
				addError(
					Message(`Unknown fragment "%s".`, fragmentSpread.Name),
					At(fragmentSpread.Position),
				)
			}
		})
	})
}
