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
	switch n.Definition.Kind {
	case ast.InputObject:
		return fmt.Sprintf(
			"%s %s: must define one or more input fields.",
			n.Definition.Kind,
			n.Definition.Name,
		)
	case ast.Enum:
		return fmt.Sprintf(
			"%s %s: must define one or more unique enum values.",
			n.Definition.Kind,
			n.Definition.Name,
		)
	default:
		return fmt.Sprintf(
			"%s %s: must define one or more fields.",
			n.Definition.Kind,
			n.Definition.Name,
		)
	}
}
