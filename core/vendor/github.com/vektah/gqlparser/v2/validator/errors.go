package validator

import (
	"fmt"

	"github.com/vektah/gqlparser/v2/ast"
)

var _ error = (*EmptyDefinitionError)(nil)

type EmptyDefinitionError struct {
	Definition *ast.Definition
}

// Error implements [error].
func (n *EmptyDefinitionError) Error() string {
	var what string
	switch n.Definition.Kind {
	case ast.InputObject:
		what = "input fields"
	case ast.Enum:
		what = "unique enum values"
	case ast.Union:
		what = "member types"
	default:
		what = "fields"
	}
	return fmt.Sprintf(
		"%s %s: must define one or more %s.",
		n.Definition.Kind,
		n.Definition.Name,
		what,
	)
}
