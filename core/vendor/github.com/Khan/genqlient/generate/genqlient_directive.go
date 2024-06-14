package generate

import (
	"fmt"
	"strings"

	"github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/parser"
)

// Represents the genqlient directive, described in detail in
// docs/genqlient_directive.graphql.
type genqlientDirective struct {
	pos       *ast.Position
	Omitempty *bool
	Pointer   *bool
	Struct    *bool
	Flatten   *bool
	Bind      string
	TypeName  string
	// FieldDirectives contains the directives to be
	// applied to specific fields via the "for" option.
	// Map from type-name -> field-name -> directive.
	FieldDirectives map[string]map[string]*genqlientDirective
}

func newGenqlientDirective(pos *ast.Position) *genqlientDirective {
	return &genqlientDirective{
		pos:             pos,
		FieldDirectives: make(map[string]map[string]*genqlientDirective),
	}
}

// Helper for String, returns the directive but without the @genqlient().
func (dir *genqlientDirective) argsString() string {
	var parts []string
	if dir.Omitempty != nil {
		parts = append(parts, fmt.Sprintf("omitempty: %v", *dir.Omitempty))
	}
	if dir.Pointer != nil {
		parts = append(parts, fmt.Sprintf("pointer: %v", *dir.Pointer))
	}
	if dir.Struct != nil {
		parts = append(parts, fmt.Sprintf("struct: %v", *dir.Struct))
	}
	if dir.Flatten != nil {
		parts = append(parts, fmt.Sprintf("flatten: %v", *dir.Flatten))
	}
	if dir.Bind != "" {
		parts = append(parts, fmt.Sprintf("bind: %v", dir.Bind))
	}
	if dir.TypeName != "" {
		parts = append(parts, fmt.Sprintf("typename: %v", dir.TypeName))
	}
	return strings.Join(parts, ", ")
}

// String is useful for debugging.
func (dir *genqlientDirective) String() string {
	lines := []string{fmt.Sprintf("@genqlient(%s)", dir.argsString())}
	for typeName, dirs := range dir.FieldDirectives {
		for fieldName, fieldDir := range dirs {
			lines = append(lines, fmt.Sprintf("@genqlient(for: %s.%s, %s)",
				typeName, fieldName, fieldDir.argsString()))
		}
	}
	return strings.Join(lines, "\n")
}

func (dir *genqlientDirective) GetOmitempty() bool   { return dir.Omitempty != nil && *dir.Omitempty }
func (dir *genqlientDirective) GetPointer() bool     { return dir.Pointer != nil && *dir.Pointer }
func (dir *genqlientDirective) PointerIsFalse() bool { return dir.Pointer != nil && !*dir.Pointer }
func (dir *genqlientDirective) GetStruct() bool      { return dir.Struct != nil && *dir.Struct }
func (dir *genqlientDirective) GetFlatten() bool     { return dir.Flatten != nil && *dir.Flatten }

func setBool(optionName string, dst **bool, v *ast.Value, pos *ast.Position) error {
	if *dst != nil {
		return errorf(pos, "conflicting values for %v", optionName)
	}
	ei, err := v.Value(nil) // no vars allowed
	if err != nil {
		return errorf(pos, "invalid boolean value %v: %v", v, err)
	}
	if b, ok := ei.(bool); ok {
		*dst = &b
		return nil
	}
	return errorf(pos, "expected boolean, got non-boolean value %T(%v)", ei, ei)
}

func setString(optionName string, dst *string, v *ast.Value, pos *ast.Position) error {
	if *dst != "" {
		return errorf(pos, "conflicting values for %v", optionName)
	}
	ei, err := v.Value(nil) // no vars allowed
	if err != nil {
		return errorf(pos, "invalid string value %v: %v", v, err)
	}
	if b, ok := ei.(string); ok {
		*dst = b
		return nil
	}
	return errorf(pos, "expected string, got non-string value %T(%v)", ei, ei)
}

// add adds to this genqlientDirective struct the settings from then given
// GraphQL directive.
//
// If there are multiple genqlient directives are applied to the same node,
// e.g.
//
//	# @genqlient(...)
//	# @genqlient(...)
//
// add will be called several times.  In this case, conflicts between the
// options are an error.
func (dir *genqlientDirective) add(graphQLDirective *ast.Directive, pos *ast.Position) error {
	if graphQLDirective.Name != "genqlient" {
		// Actually we just won't get here; we only get here if the line starts
		// with "# @genqlient", unless there's some sort of bug.
		return errorf(pos, "the only valid comment-directive is @genqlient, got %v", graphQLDirective.Name)
	}

	// First, see if this directive has a "for" option;
	// if it does, the rest of our work will operate on the
	// appropriate place in FieldDirectives.
	var err error
	forField := ""
	for _, arg := range graphQLDirective.Arguments {
		if arg.Name == "for" {
			if forField != "" {
				return errorf(pos, `@genqlient directive had "for:" twice`)
			}
			err = setString("for", &forField, arg.Value, pos)
			if err != nil {
				return err
			}
		}
	}
	if forField != "" {
		forParts := strings.Split(forField, ".")
		if len(forParts) != 2 {
			return errorf(pos, `for must be of the form "MyType.myField"`)
		}
		typeName, fieldName := forParts[0], forParts[1]

		fieldDir := newGenqlientDirective(pos)
		if dir.FieldDirectives[typeName] == nil {
			dir.FieldDirectives[typeName] = make(map[string]*genqlientDirective)
		}
		dir.FieldDirectives[typeName][fieldName] = fieldDir

		// Now, the rest of the function will operate on fieldDir.
		dir = fieldDir
	}

	// Now parse the rest of the arguments.
	for _, arg := range graphQLDirective.Arguments {
		switch arg.Name {
		// TODO(benkraft): Use reflect and struct tags?
		case "omitempty":
			err = setBool("omitempty", &dir.Omitempty, arg.Value, pos)
		case "pointer":
			err = setBool("pointer", &dir.Pointer, arg.Value, pos)
		case "struct":
			err = setBool("struct", &dir.Struct, arg.Value, pos)
		case "flatten":
			err = setBool("flatten", &dir.Flatten, arg.Value, pos)
		case "bind":
			err = setString("bind", &dir.Bind, arg.Value, pos)
		case "typename":
			err = setString("typename", &dir.TypeName, arg.Value, pos)
		case "for":
			// handled above
		default:
			return errorf(pos, "unknown argument %v for @genqlient", arg.Name)
		}
		if err != nil {
			return err
		}
	}

	return nil
}

func (dir *genqlientDirective) validate(node interface{}, schema *ast.Schema) error {
	// TODO(benkraft): This function has a lot of duplicated checks, figure out
	// how to organize them better to avoid the duplication.
	for typeName, byField := range dir.FieldDirectives {
		typ, ok := schema.Types[typeName]
		if !ok {
			return errorf(dir.pos, `for got invalid type-name "%s"`, typeName)
		}
		for fieldName, fieldDir := range byField {
			var field *ast.FieldDefinition
			for _, typeField := range typ.Fields {
				if typeField.Name == fieldName {
					field = typeField
					break
				}
			}
			if field == nil {
				return errorf(fieldDir.pos,
					`for got invalid field-name "%s" for type "%s"`,
					fieldName, typeName)
			}

			// All options except struct and flatten potentially apply.  (I
			// mean in theory you could apply them here, but since they require
			// per-use validation, it would be a bit tricky, and the use case
			// is not clear.)
			if fieldDir.Struct != nil || fieldDir.Flatten != nil {
				return errorf(fieldDir.pos, "struct and flatten can't be used via for")
			}

			if fieldDir.Omitempty != nil && field.Type.NonNull {
				return errorf(fieldDir.pos, "omitempty may only be used on optional arguments")
			}

			if fieldDir.TypeName != "" && fieldDir.Bind != "" && fieldDir.Bind != "-" {
				return errorf(fieldDir.pos, "typename and bind may not be used together")
			}
		}
	}

	switch node := node.(type) {
	case *ast.OperationDefinition:
		if dir.Bind != "" {
			return errorf(dir.pos, "bind may not be applied to the entire operation")
		}

		// Anything else is valid on the entire operation; it will just apply
		// to whatever it is relevant to.
		return nil
	case *ast.FragmentDefinition:
		if dir.Bind != "" {
			// TODO(benkraft): Implement this if people find it useful.
			return errorf(dir.pos, "bind is not implemented for named fragments")
		}

		if dir.Struct != nil {
			return errorf(dir.pos, "struct is only applicable to fields, not frragment-definitions")
		}

		// Like operations, anything else will just apply to the entire
		// fragment.
		return nil
	case *ast.VariableDefinition:
		if dir.Omitempty != nil && node.Type.NonNull {
			return errorf(dir.pos, "omitempty may only be used on optional arguments")
		}

		if dir.Struct != nil {
			return errorf(dir.pos, "struct is only applicable to fields, not variable-definitions")
		}

		if dir.Flatten != nil {
			return errorf(dir.pos, "flatten is only applicable to fields, not variable-definitions")
		}

		if len(dir.FieldDirectives) > 0 {
			return errorf(dir.pos, "for is only applicable to operations and arguments")
		}

		if dir.TypeName != "" && dir.Bind != "" && dir.Bind != "-" {
			return errorf(dir.pos, "typename and bind may not be used together")
		}

		return nil
	case *ast.Field:
		if dir.Omitempty != nil {
			return errorf(dir.pos, "omitempty is not applicable to variables, not fields")
		}

		typ := schema.Types[node.Definition.Type.Name()]
		if dir.Struct != nil {
			if err := validateStructOption(typ, node.SelectionSet, dir.pos); err != nil {
				return err
			}
		}

		if dir.Flatten != nil {
			if _, err := validateFlattenOption(typ, node.SelectionSet, dir.pos); err != nil {
				return err
			}
		}

		if len(dir.FieldDirectives) > 0 {
			return errorf(dir.pos, "for is only applicable to operations and arguments")
		}

		if dir.TypeName != "" && dir.Bind != "" && dir.Bind != "-" {
			return errorf(dir.pos, "typename and bind may not be used together")
		}

		return nil
	default:
		return errorf(dir.pos, "invalid @genqlient directive location: %T", node)
	}
}

func validateStructOption(
	typ *ast.Definition,
	selectionSet ast.SelectionSet,
	pos *ast.Position,
) error {
	if typ.Kind != ast.Interface && typ.Kind != ast.Union {
		return errorf(pos, "struct is only applicable to interface-typed fields")
	}

	// Make sure that all the requested fields apply to the interface itself
	// (not just certain implementations).
	for _, selection := range selectionSet {
		switch selection.(type) {
		case *ast.Field:
			// fields are fine.
		case *ast.InlineFragment, *ast.FragmentSpread:
			// Fragments aren't allowed. In principle we could allow them under
			// the condition that the fragment applies to the whole interface
			// (not just one implementation; and so on recursively), and for
			// fragment spreads additionally that the fragment has the same
			// option applied to it, but it seems more trouble than it's worth
			// right now.
			return errorf(pos, "struct is not allowed for types with fragments")
		}
	}
	return nil
}

func validateFlattenOption(
	typ *ast.Definition,
	selectionSet ast.SelectionSet,
	pos *ast.Position,
) (index int, err error) {
	index = -1
	if len(selectionSet) == 0 {
		return -1, errorf(pos, "flatten is not allowed for leaf fields")
	}

	for i, selection := range selectionSet {
		switch selection := selection.(type) {
		case *ast.Field:
			// If the field is auto-added __typename, ignore it for flattening
			// purposes.
			if selection.Name == "__typename" && selection.Position == nil {
				continue
			}
			// Type-wise, it's no harder to implement flatten for fields, but
			// it requires new logic in UnmarshalJSON.  We can add that if it
			// proves useful relative to its complexity.
			return -1, errorf(pos, "flatten is not yet supported for fields (only fragment spreads)")

		case *ast.InlineFragment:
			// Inline fragments aren't allowed. In principle there's nothing
			// stopping us from allowing them (under the same type-match
			// conditions as fragment spreads), but there's little value to it.
			return -1, errorf(pos, "flatten is not allowed for selections with inline fragments")

		case *ast.FragmentSpread:
			if index != -1 {
				return -1, errorf(pos, "flatten is not allowed for fields with multiple selections")
			} else if !fragmentMatches(typ, selection.Definition.Definition) {
				// We don't let you flatten
				//  field { # type: FieldType
				//		...Fragment # type: FragmentType
				//	}
				// unless FragmentType implements FieldType, because otherwise
				// what do we do if we get back a type that doesn't implement
				// FragmentType?
				return -1, errorf(pos,
					"flatten is not allowed for fields with fragment-spreads "+
						"unless the field-type implements the fragment-type; "+
						"field-type %s does not implement fragment-type %s",
					typ.Name, selection.Definition.Definition.Name)
			}
			index = i
		}
	}
	return index, nil
}

func fillDefaultBool(target **bool, defaults ...*bool) {
	if *target != nil {
		return
	}

	for _, val := range defaults {
		if val != nil {
			*target = val
			return
		}
	}
}

func fillDefaultString(target *string, defaults ...string) {
	if *target != "" {
		return
	}

	for _, val := range defaults {
		if val != "" {
			*target = val
			return
		}
	}
}

// merge updates the receiver, which is a directive applied to some node, with
// the information from the directive applied to the fragment or operation
// containing that node.  (The update is in-place.)
//
// Note this has slightly different semantics than .add(), see inline for
// details.
//
// parent is as described in parsePrecedingComment.  operationDirective is the
// directive applied to this operation or fragment.
func (dir *genqlientDirective) mergeOperationDirective(
	node interface{},
	parentIfInputField *ast.Definition,
	operationDirective *genqlientDirective,
) {
	// We'll set forField to the `@genqlient(for: "<this field>", ...)`
	// directive from our operation/fragment, if any.
	var forField *genqlientDirective
	switch field := node.(type) {
	case *ast.Field: // query field
		typeName := field.ObjectDefinition.Name
		forField = operationDirective.FieldDirectives[typeName][field.Name]
	case *ast.FieldDefinition: // input-type field
		forField = operationDirective.FieldDirectives[parentIfInputField.Name][field.Name]
	}
	// Just to simplify nil-checking in the code below:
	if forField == nil {
		forField = newGenqlientDirective(nil)
	}

	// Now fill defaults; in general local directive wins over the "for" field
	// directive wins over the operation directive.
	fillDefaultBool(&dir.Omitempty, forField.Omitempty, operationDirective.Omitempty)
	fillDefaultBool(&dir.Pointer, forField.Pointer, operationDirective.Pointer)
	// struct and flatten aren't settable via "for".
	fillDefaultBool(&dir.Struct, operationDirective.Struct)
	fillDefaultBool(&dir.Flatten, operationDirective.Flatten)
	fillDefaultString(&dir.Bind, forField.Bind, operationDirective.Bind)
	// typename isn't settable on the operation (when set there it replies to
	// the response-type).
	fillDefaultString(&dir.TypeName, forField.TypeName)
}

// parsePrecedingComment looks at the comment right before this node, and
// returns the genqlient directive applied to it (or an empty one if there is
// none), the remaining human-readable comment (or "" if there is none), and an
// error if the directive is invalid.
//
// queryOptions are the options to be applied to this entire query (or
// fragment); the local options will be merged into those.  It should be nil if
// we are parsing the directive on the entire query.
//
// parentIfInputField need only be set if node is an input-type field; it
// should be the type containing this field.  (We can get this from gqlparser
// in other cases, but not input-type fields.)
func (g *generator) parsePrecedingComment(
	node interface{},
	parentIfInputField *ast.Definition,
	pos *ast.Position,
	queryOptions *genqlientDirective,
) (comment string, directive *genqlientDirective, err error) {
	directive = newGenqlientDirective(pos)
	hasDirective := false

	// For directives on genqlient-generated nodes, we don't actually need to
	// parse anything.  (But we do need to merge below.)
	var commentLines []string
	if pos != nil && pos.Src != nil {
		sourceLines := strings.Split(pos.Src.Input, "\n")
		for i := pos.Line - 1; i > 0; i-- {
			line := strings.TrimSpace(sourceLines[i-1])
			trimmed := strings.TrimSpace(strings.TrimPrefix(line, "#"))
			if strings.HasPrefix(line, "# @genqlient") {
				hasDirective = true
				var graphQLDirective *ast.Directive
				graphQLDirective, err = parseDirective(trimmed, pos)
				if err != nil {
					return "", nil, err
				}
				err = directive.add(graphQLDirective, pos)
				if err != nil {
					return "", nil, err
				}
			} else if strings.HasPrefix(line, "#") {
				commentLines = append(commentLines, trimmed)
			} else {
				break
			}
		}
	}

	if hasDirective { // (else directive is empty)
		err = directive.validate(node, g.schema)
		if err != nil {
			return "", nil, err
		}
	}

	if queryOptions != nil {
		// If we are part of an operation/fragment, merge its options in.
		directive.mergeOperationDirective(node, parentIfInputField, queryOptions)

		// TODO(benkraft): Really we should do all the validation after
		// merging, probably?  But this is the only check that can fail only
		// after merging, and it's a bit tricky because the "does not apply"
		// checks may need to happen before merging so we know where the
		// directive "is".
		if directive.TypeName != "" && directive.Bind != "" && directive.Bind != "-" {
			return "", nil, errorf(directive.pos, "typename and bind may not be used together")
		}
	}

	reverse(commentLines)

	return strings.TrimSpace(strings.Join(commentLines, "\n")), directive, nil
}

func parseDirective(line string, pos *ast.Position) (*ast.Directive, error) {
	// HACK: parse the "directive" by making a fake query containing it.
	fakeQuery := fmt.Sprintf("query %v { field }", line)
	doc, err := parser.ParseQuery(&ast.Source{Input: fakeQuery})
	if err != nil {
		return nil, errorf(pos, "invalid genqlient directive: %v", err)
	}
	return doc.Operations[0].Directives[0], nil
}
