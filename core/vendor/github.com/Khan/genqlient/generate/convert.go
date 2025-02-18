package generate

// This file implements the core type-generation logic of genqlient, whereby we
// traverse an operation-definition (and the schema against which it will be
// executed), and convert that into Go types.  It returns data structures
// representing the types to be generated; these are defined, and converted
// into code, in types.go.
//
// The entrypoints are convertOperation, which builds the response-type for a
// query, and convertArguments, which builds the argument-types.

import (
	"fmt"
	"sort"

	"github.com/vektah/gqlparser/v2/ast"
)

// getType returns the existing type in g.typeMap with the given name, if any,
// and an error if such type is incompatible with this one.
//
// This is useful as an early-out and a safety-check when generating types; if
// the type has already been generated we can skip generating it again.  (This
// is necessary to handle recursive input types, and an optimization in other
// cases.)
func (g *generator) getType(
	goName, graphQLName string,
	selectionSet ast.SelectionSet,
	pos *ast.Position,
) (goType, error) {
	typ, ok := g.typeMap[goName]
	if !ok {
		return nil, nil
	}

	if typ.GraphQLTypeName() != graphQLName {
		return typ, errorf(
			pos, "conflicting definition for %s; this can indicate either "+
				"a genqlient internal error, a conflict between user-specified "+
				"type-names, or some very tricksy GraphQL field/type names: "+
				"expected GraphQL type %s, got %s",
			goName, typ.GraphQLTypeName(), graphQLName)
	}

	expectedSelectionSet := typ.SelectionSet()
	if err := selectionsMatch(pos, selectionSet, expectedSelectionSet); err != nil {
		return typ, errorf(
			pos, "conflicting definition for %s; this can indicate either "+
				"a genqlient internal error, a conflict between user-specified "+
				"type-names, or some very tricksy GraphQL field/type names: %v",
			goName, err)
	}

	return typ, nil
}

// addType inserts the type into g.typeMap, checking for conflicts.
//
// The conflict-checking is as described in getType.  Note we have to do it
// here again, even if the caller has already called getType, because the
// caller in between may have generated new types, which potentially creates
// new conflicts.
//
// Returns an already-existing type if found, and otherwise the given type.
func (g *generator) addType(typ goType, goName string, pos *ast.Position) (goType, error) {
	otherTyp, err := g.getType(goName, typ.GraphQLTypeName(), typ.SelectionSet(), pos)
	if otherTyp != nil || err != nil {
		return otherTyp, err
	}
	g.typeMap[goName] = typ
	return typ, nil
}

// baseTypeForOperation returns the definition of the GraphQL type to which the
// root of the operation corresponds, e.g. the "Query" or "Mutation" type.
func (g *generator) baseTypeForOperation(operation ast.Operation) (*ast.Definition, error) {
	switch operation {
	case ast.Query:
		return g.schema.Query, nil
	case ast.Mutation:
		return g.schema.Mutation, nil
	case ast.Subscription:
		if !g.Config.AllowBrokenFeatures {
			return nil, errorf(nil, "genqlient does not yet support subscriptions")
		}
		return g.schema.Subscription, nil
	default:
		return nil, errorf(nil, "unexpected operation: %v", operation)
	}
}

// convertOperation builds the response-type into which the given operation's
// result will be unmarshaled.
func (g *generator) convertOperation(
	operation *ast.OperationDefinition,
	queryOptions *genqlientDirective,
) (goType, error) {
	name := operation.Name + "Response"
	namePrefix := newPrefixList(operation.Name)
	if queryOptions.TypeName != "" {
		name = queryOptions.TypeName
		namePrefix = newPrefixList(queryOptions.TypeName)
	}

	baseType, err := g.baseTypeForOperation(operation.Operation)
	if err != nil {
		return nil, errorf(operation.Position, "%v", err)
	}

	// Instead of calling out to convertType/convertDefinition, we do our own
	// thing, because we want to do a few things differently, and because we
	// know we have an object type, so we can include only that case.
	fields, err := g.convertSelectionSet(
		namePrefix, operation.SelectionSet, baseType, queryOptions)
	if err != nil {
		return nil, err
	}

	// It's not common to use a fragment-spread for the whole query, but you
	// can if you want two queries to return the same type!
	if queryOptions.GetFlatten() {
		i, err := validateFlattenOption(baseType, operation.SelectionSet, operation.Position)
		if err == nil {
			return fields[i].GoType, nil
		}
	}

	goType := &goStructType{
		GoName: name,
		descriptionInfo: descriptionInfo{
			CommentOverride: fmt.Sprintf(
				"%v is returned by %v on success.", name, operation.Name),
			GraphQLName: baseType.Name,
			// omit the GraphQL description for baseType; it's uninteresting.
		},
		Fields:    fields,
		Selection: operation.SelectionSet,
		Generator: g,
	}

	return g.addType(goType, goType.GoName, operation.Position)
}

var builtinTypes = map[string]string{
	// GraphQL guarantees int32 is enough, but using int seems more idiomatic
	"Int":     "int",
	"Float":   "float64",
	"String":  "string",
	"Boolean": "bool",
	"ID":      "string",
}

// convertArguments builds the type of the GraphQL arguments to the given
// operation.
//
// This type is not exposed to the user; it's just used internally in the
// unmarshaler; and it's used as a container
func (g *generator) convertArguments(
	operation *ast.OperationDefinition,
	queryOptions *genqlientDirective,
) (*goStructType, error) {
	if len(operation.VariableDefinitions) == 0 {
		return nil, nil
	}
	name := "__" + operation.Name + "Input"
	fields := make([]*goStructField, len(operation.VariableDefinitions))
	for i, arg := range operation.VariableDefinitions {
		if goKeywords[arg.Variable] {
			return nil, errorf(arg.Position, "variable name must not be a go keyword")
		}

		_, options, err := g.parsePrecedingComment(arg, nil, arg.Position, queryOptions)
		if err != nil {
			return nil, err
		}

		goName := upperFirst(arg.Variable)
		// Some of the arguments don't apply here, namely the name-prefix (see
		// names.go) and the selection-set (we use all the input type's fields,
		// and so on recursively).  See also the `case ast.InputObject` in
		// convertDefinition, below.
		goTyp, err := g.convertType(nil, arg.Type, nil, options, queryOptions)
		if err != nil {
			return nil, err
		}

		fields[i] = &goStructField{
			GoName:      goName,
			GoType:      goTyp,
			JSONName:    arg.Variable,
			GraphQLName: arg.Variable,
			Omitempty:   options.GetOmitempty(),
		}
	}
	goTyp := &goStructType{
		GoName:    name,
		Fields:    fields,
		Selection: nil,
		IsInput:   true,
		descriptionInfo: descriptionInfo{
			CommentOverride: fmt.Sprintf("%s is used internally by genqlient", name),
			// fake name, used by addType
			GraphQLName: name,
		},
		Generator: g,
	}
	goTypAgain, err := g.addType(goTyp, goTyp.GoName, operation.Position)
	if err != nil {
		return nil, err
	}
	goTyp, ok := goTypAgain.(*goStructType)
	if !ok {
		return nil, errorf(
			operation.Position, "internal error: input type was %T", goTypAgain)
	}
	return goTyp, nil
}

// convertType decides the Go type we will generate corresponding to a
// particular GraphQL type.  In this context, "type" represents the type of a
// field, and may be a list or a reference to a named type, with or without the
// "non-null" annotation.
func (g *generator) convertType(
	namePrefix *prefixList,
	typ *ast.Type,
	selectionSet ast.SelectionSet,
	options, queryOptions *genqlientDirective,
) (goType, error) {
	// We check for local bindings here, so that you can bind, say, a
	// `[String!]` to a struct instead of a slice.  Global bindings can only
	// bind GraphQL named types, at least for now.
	localBinding := options.Bind
	if localBinding != "" && localBinding != "-" {
		goRef, err := g.ref(localBinding)
		// TODO(benkraft): Add syntax to specify a custom (un)marshaler, if
		// it proves useful.
		return &goOpaqueType{GoRef: goRef, GraphQLName: typ.Name()}, err
	}

	if typ.Elem != nil {
		// Type is a list.
		elem, err := g.convertType(
			namePrefix, typ.Elem, selectionSet, options, queryOptions)
		return &goSliceType{elem}, err
	}

	// If this is a builtin type or custom scalar, just refer to it.
	def := g.schema.Types[typ.Name()]
	goTyp, err := g.convertDefinition(
		namePrefix, def, typ.Position, selectionSet, options, queryOptions)

	if g.getStructReference(def) {
		if options.Pointer == nil || *options.Pointer {
			goTyp = &goPointerType{goTyp}
		}
		if options.Omitempty == nil || *options.Omitempty {
			oe := true
			options.Omitempty = &oe
		}
	} else if !options.PointerIsFalse() && (options.GetPointer() || (!typ.NonNull && g.Config.Optional == "pointer")) {
		// Whatever we get, wrap it in a pointer.  (Because of the way the
		// options work, recursing here isn't as connvenient.)
		// Note this does []*T or [][]*T, not e.g. *[][]T.  See #16.
		goTyp = &goPointerType{goTyp}
	} else if !typ.NonNull && g.Config.Optional == "generic" {
		var genericRef string
		genericRef, err = g.ref(g.Config.OptionalGenericType)
		if err != nil {
			return nil, err
		}

		goTyp = &goGenericType{
			GoGenericRef: genericRef,
			Elem:         goTyp,
		}
	}
	return goTyp, err
}

// getStructReference decides if a field should be of pointer type and have the omitempty flag set.
func (g *generator) getStructReference(
	def *ast.Definition,
) bool {
	return g.Config.StructReferences &&
		(def.Kind == ast.Object || def.Kind == ast.InputObject)
}

// convertDefinition decides the Go type we will generate corresponding to a
// particular GraphQL named type.
//
// In this context, "definition" (and "named type") refer to an
// *ast.Definition, which represents the definition of a type in the GraphQL
// schema, which may be referenced by a field-type (see convertType).
func (g *generator) convertDefinition(
	namePrefix *prefixList,
	def *ast.Definition,
	pos *ast.Position,
	selectionSet ast.SelectionSet,
	options, queryOptions *genqlientDirective,
) (goType, error) {
	// Check if we should use an existing type.  (This is usually true for
	// GraphQL scalars, but we allow you to bind non-scalar types too, if you
	// want, subject to the caveats described in Config.Bindings.)  Local
	// bindings are checked in the caller (convertType) and never get here,
	// unless the binding is "-" which means "ignore the global binding".
	globalBinding, ok := g.Config.Bindings[def.Name]
	if ok && options.Bind != "-" {
		if options.TypeName != "" {
			// The option position (in the query) is more useful here.
			return nil, errorf(options.pos,
				"typename option conflicts with global binding for %s; "+
					"use `bind: \"-\"` to override it", def.Name)
		}
		if def.Kind == ast.Object || def.Kind == ast.Interface || def.Kind == ast.Union {
			err := g.validateBindingSelection(
				def.Name, globalBinding, pos, selectionSet)
			if err != nil {
				return nil, err
			}
		}
		goRef, err := g.ref(globalBinding.Type)
		return &goOpaqueType{
			GoRef:       goRef,
			GraphQLName: def.Name,
			Marshaler:   globalBinding.Marshaler,
			Unmarshaler: globalBinding.Unmarshaler,
		}, err
	}
	goBuiltinName, ok := builtinTypes[def.Name]
	if ok && options.TypeName == "" {
		return &goOpaqueType{GoRef: goBuiltinName, GraphQLName: def.Name}, nil
	}

	// Determine the name to use for this type.
	var name string
	if options.TypeName != "" {
		if goKeywords[options.TypeName] {
			return nil, errorf(pos, "typename option must not be a go keyword")
		}
		// If the user specified a name, use it!
		name = options.TypeName
		if namePrefix != nil && namePrefix.head == name && namePrefix.tail == nil {
			// Special case: if this name is also the only component of the
			// name-prefix, append the type-name anyway.  This happens when you
			// assign a type name to an interface type, and we are generating
			// one of its implementations.
			name = makeLongTypeName(namePrefix, def.Name)
		}
		// (But the prefix is shared.)
		namePrefix = newPrefixList(options.TypeName)
	} else if def.Kind == ast.InputObject || def.Kind == ast.Enum {
		// If we're an input-object or enum, there is only one type we will
		// ever possibly generate for this type, so we don't need any of the
		// qualifiers.  This is especially helpful because the caller is very
		// likely to need to reference these types in their code.
		name = upperFirst(def.Name)
		// (namePrefix is ignored in this case.)
	} else {
		// Else, construct a name using the usual algorithm (see names.go).
		name = makeTypeName(namePrefix, def.Name)
	}

	// If we already generated the type, we can skip it as long as it matches
	// (and must fail if it doesn't).  (This can happen for input/enum types,
	// types of fields of interfaces, when options.TypeName is set, or, of
	// course, on invalid configuration or internal error.)
	existing, err := g.getType(name, def.Name, selectionSet, pos)
	if existing != nil || err != nil {
		return existing, err
	}

	desc := descriptionInfo{
		// TODO(benkraft): Copy any comment above this selection-set?
		GraphQLDescription: def.Description,
		GraphQLName:        def.Name,
	}

	// The struct option basically means "treat this as if it were an object".
	// (It only applies if valid; this is important if you said the whole
	// query should have `struct: true`.)
	kind := def.Kind
	if options.GetStruct() && validateStructOption(def, selectionSet, pos) == nil {
		kind = ast.Object
	}
	switch kind {
	case ast.Object:
		fields, err := g.convertSelectionSet(
			namePrefix, selectionSet, def, queryOptions)
		if err != nil {
			return nil, err
		}
		if options.GetFlatten() {
			// As with struct, flatten only applies if valid, important if you
			// applied it to the whole query.
			// TODO(benkraft): This is a slightly fragile way to do this;
			// figure out a good way to do it before/while constructing the
			// fields, rather than after.
			i, err := validateFlattenOption(def, selectionSet, pos)
			if err == nil {
				return fields[i].GoType, nil
			}
		}

		goType := &goStructType{
			GoName:          name,
			Fields:          fields,
			Selection:       selectionSet,
			descriptionInfo: desc,
			Generator:       g,
		}
		return g.addType(goType, goType.GoName, pos)

	case ast.InputObject:
		goType := &goStructType{
			GoName:          name,
			Fields:          make([]*goStructField, len(def.Fields)),
			descriptionInfo: desc,
			IsInput:         true,
			Generator:       g,
		}
		// To handle recursive types, we need to add the type to the type-map
		// *before* converting its fields.
		_, err := g.addType(goType, goType.GoName, pos)
		if err != nil {
			return nil, err
		}

		for i, field := range def.Fields {
			_, fieldOptions, err := g.parsePrecedingComment(
				field, def, field.Position, queryOptions)
			if err != nil {
				return nil, err
			}

			goName := upperFirst(field.Name)
			// Several of the arguments don't really make sense here:
			// (note field.Type is necessarily a scalar, input, or enum)
			//  - namePrefix is ignored for input types and enums (see
			//    names.go) and for scalars (they use client-specified
			//    names)
			//  - selectionSet is ignored for input types, because we
			//    just use all fields of the type; and it's nonexistent
			//    for scalars and enums, our only other possible types
			// TODO(benkraft): Can we refactor to avoid passing the values that
			// will be ignored?  We know field.Type is a scalar, enum, or input
			// type.  But plumbing that is a bit tricky in practice.
			fieldGoType, err := g.convertType(
				namePrefix, field.Type, nil, fieldOptions, queryOptions)
			if err != nil {
				return nil, err
			}

			goType.Fields[i] = &goStructField{
				GoName:      goName,
				GoType:      fieldGoType,
				JSONName:    field.Name,
				GraphQLName: field.Name,
				Description: field.Description,
				Omitempty:   fieldOptions.GetOmitempty(),
			}
		}
		return goType, nil

	case ast.Interface, ast.Union:
		sharedFields, err := g.convertSelectionSet(
			namePrefix, selectionSet, def, queryOptions)
		if err != nil {
			return nil, err
		}
		// Flatten can only flatten if there is only one field (plus perhaps
		// __typename), and it's shared.
		if options.GetFlatten() {
			i, err := validateFlattenOption(def, selectionSet, pos)
			if err == nil {
				return sharedFields[i].GoType, nil
			}
		}

		implementationTypes := g.schema.GetPossibleTypes(def)
		// Make sure we generate stable output by sorting the types by name when we get them
		sort.Slice(implementationTypes, func(i, j int) bool { return implementationTypes[i].Name < implementationTypes[j].Name })
		goType := &goInterfaceType{
			GoName:          name,
			SharedFields:    sharedFields,
			Implementations: make([]*goStructType, len(implementationTypes)),
			Selection:       selectionSet,
			descriptionInfo: desc,
		}

		for i, implDef := range implementationTypes {
			// TODO(benkraft): In principle we should skip generating a Go
			// field for __typename each of these impl-defs if you didn't
			// request it (and it was automatically added by
			// preprocessQueryDocument).  But in practice it doesn't really
			// hurt, and would be extra work to avoid, so we just leave it.
			implTyp, err := g.convertDefinition(
				namePrefix, implDef, pos, selectionSet, options, queryOptions)
			if err != nil {
				return nil, err
			}

			implStructTyp, ok := implTyp.(*goStructType)
			if !ok { // (should never happen on a valid schema)
				return nil, errorf(
					pos, "interface %s had non-object implementation %s",
					def.Name, implDef.Name)
			}
			goType.Implementations[i] = implStructTyp
		}
		return g.addType(goType, goType.GoName, pos)

	case ast.Enum:
		goType := &goEnumType{
			GoName:      name,
			GraphQLName: def.Name,
			Description: def.Description,
			Values:      make([]goEnumValue, len(def.EnumValues)),
		}
		goNames := make(map[string]*goEnumValue, len(def.EnumValues))
		for i, val := range def.EnumValues {
			goName := g.Config.Casing.enumValueName(name, def, val)
			if conflict := goNames[goName]; conflict != nil {
				return nil, errorf(val.Position,
					"enum values %s and %s have conflicting Go name %s; "+
						"add 'all_enums: raw' or 'enums: %v: raw' "+
						"to 'casing' in genqlient.yaml to fix",
					val.Name, conflict.GraphQLName, goName, def.Name)
			}

			goType.Values[i] = goEnumValue{
				GoName:      goName,
				GraphQLName: val.Name,
				Description: val.Description,
			}
			goNames[goName] = &goType.Values[i]
		}
		return g.addType(goType, goType.GoName, pos)

	case ast.Scalar:
		if builtinTypes[def.Name] != "" {
			// In this case, the user asked for a custom Go type-name
			// for a built-in type, e.g. `type MyString string`.
			goType := &goTypenameForBuiltinType{
				GoTypeName:    name,
				GoBuiltinName: builtinTypes[def.Name],
				GraphQLName:   def.Name,
			}
			return g.addType(goType, goType.GoTypeName, pos)
		}

		// (If you had an entry in bindings, we would have returned it above.)
		return nil, errorf(
			pos, "unknown scalar %v: please add it to \"bindings\" in genqlient.yaml"+
				"\nExample: https://github.com/Khan/genqlient/blob/main/example/genqlient.yaml#L12", def.Name)
	default:
		return nil, errorf(pos, "unexpected kind: %v", def.Kind)
	}
}

// convertSelectionSet converts a GraphQL selection-set into a list of
// corresponding Go struct-fields (and their Go types)
//
// A selection-set is a list of fields within braces like `{ myField }`, as
// appears at the toplevel of a query, in a field's sub-selections, or within
// an inline or named fragment.
//
// containingTypedef is the type-def whose fields we are selecting, and may be
// an object type or an interface type.  In the case of interfaces, we'll call
// convertSelectionSet once for the interface, and once for each
// implementation.
func (g *generator) convertSelectionSet(
	namePrefix *prefixList,
	selectionSet ast.SelectionSet,
	containingTypedef *ast.Definition,
	queryOptions *genqlientDirective,
) ([]*goStructField, error) {
	fields := make([]*goStructField, 0, len(selectionSet))
	for _, selection := range selectionSet {
		_, selectionOptions, err := g.parsePrecedingComment(
			selection, nil, selection.GetPosition(), queryOptions)
		if err != nil {
			return nil, err
		}

		switch selection := selection.(type) {
		case *ast.Field:
			field, err := g.convertField(
				namePrefix, selection, selectionOptions, queryOptions)
			if err != nil {
				return nil, err
			}
			fields = append(fields, field)
		case *ast.FragmentSpread:
			maybeField, err := g.convertFragmentSpread(selection, containingTypedef)
			if err != nil {
				return nil, err
			} else if maybeField != nil {
				fields = append(fields, maybeField)
			}
		case *ast.InlineFragment:
			// (Note this will return nil, nil if the fragment doesn't apply to
			// this type.)
			fragmentFields, err := g.convertInlineFragment(
				namePrefix, selection, containingTypedef, queryOptions)
			if err != nil {
				return nil, err
			}
			fields = append(fields, fragmentFields...)
		default:
			return nil, errorf(nil, "invalid selection type: %T", selection)
		}
	}

	// We need to deduplicate, if you asked for
	//	{ id, id, id, ... on SubType { id } }
	// (which, yes, is legal) we'll treat that as just { id }.
	uniqFields := make([]*goStructField, 0, len(selectionSet))
	fragmentNames := make(map[string]bool, len(selectionSet))
	fieldNames := make(map[string]bool, len(selectionSet))
	for _, field := range fields {
		// If you embed a field twice via a named fragment, we keep both, even
		// if there are complicated overlaps, since they are separate types to
		// us.  (See also the special handling for IsEmbedded in
		// unmarshal.go.tmpl.)
		//
		// But if you spread the samenamed fragment twice, e.g.
		//	{ ...MyFragment, ... on SubType { ...MyFragment } }
		// we'll still deduplicate that.
		if field.JSONName == "" {
			name := field.GoType.Reference()
			if fragmentNames[name] {
				continue
			}
			uniqFields = append(uniqFields, field)
			fragmentNames[name] = true
			continue
		}

		// GraphQL (and, effectively, JSON) requires that all fields with the
		// same alias (JSON-name) must be the same (i.e. refer to the same
		// field), so that's how we deduplicate.
		if fieldNames[field.JSONName] {
			// GraphQL (and, effectively, JSON) forbids you from having two
			// fields with the same alias (JSON-name) that refer to different
			// GraphQL fields.  But it does allow you to have the same field
			// with different selections (subject to some additional rules).
			// We say: that's too complicated! and allow duplicate fields
			// only if they're "leaf" types (enum or scalar).
			switch field.GoType.Unwrap().(type) {
			case *goOpaqueType, *goEnumType:
				// Leaf field; we can just deduplicate.
				// Note GraphQL already guarantees that the conflicting field
				// has scalar/enum type iff this field does:
				// https://spec.graphql.org/draft/#SameResponseShape()
				continue
			case *goStructType, *goInterfaceType:
				// TODO(benkraft): Keep track of the position of each
				// selection, so we can put this error on the right line.
				return nil, errorf(nil,
					"genqlient doesn't allow duplicate fields with different selections "+
						"(see https://github.com/Khan/genqlient/issues/64); "+
						"duplicate field: %s.%s", containingTypedef.Name, field.JSONName)
			default:
				return nil, errorf(nil, "unexpected field-type: %T", field.GoType.Unwrap())
			}
		}
		uniqFields = append(uniqFields, field)
		fieldNames[field.JSONName] = true
	}
	return uniqFields, nil
}

// fragmentMatches returns true if the given fragment is "active" when applied
// to the given type.
//
// "Active" here means "the fragment's fields will be returned on all objects
// of the given type", which is true when the given type is or implements
// the fragment's type.  This is distinct from the rules for when a fragment
// spread is legal, which is true when the fragment would be active for *any*
// of the concrete types the spread-context could have (see the [GraphQL spec]
// or docs/design.md).
//
// containingTypedef is as described in convertInlineFragment, below.
// fragmentTypedef is the definition of the fragment's type-condition, i.e. the
// definition of MyType in a fragment `on MyType`.
//
// [GraphQL spec]: https://spec.graphql.org/draft/#sec-Fragment-Spreads
func fragmentMatches(containingTypedef, fragmentTypedef *ast.Definition) bool {
	if containingTypedef.Name == fragmentTypedef.Name {
		return true
	}
	for _, iface := range containingTypedef.Interfaces {
		// Note we don't need to recurse into the interfaces here, because in
		// GraphQL types must list all the interfaces they implement, including
		// all types those interfaces implement ([spec]).  Actually, at present
		// gqlparser doesn't even support interfaces implementing other
		// interfaces, but our code would handle that too.
		//
		// [spec]: https://spec.graphql.org/draft/#sec-Interfaces.Interfaces-Implementing-Interfaces
		if iface == fragmentTypedef.Name {
			return true
		}
	}

	// Handle the special case where the fragment is on a union, then the
	// fragment can match any of the types in the union.
	if fragmentTypedef.Kind == ast.Union {
		for _, typeName := range fragmentTypedef.Types {
			if typeName == containingTypedef.Name {
				return true
			}
		}
	}

	return false
}

// convertInlineFragment converts a single GraphQL inline fragment
// (`... on MyType { myField }`) into Go struct-fields.
//
// containingTypedef is the type-def corresponding to the type into which we
// are spreading; it may be either an interface type (when spreading into one)
// or an object type (when writing the implementations of such an interface, or
// when using an inline fragment in an object type which is rare).  If the
// given fragment does not apply to that type, this function returns nil, nil.
//
// In general, we treat such fragments' fields as if they were fields of the
// parent selection-set (except of course they are only included in types the
// fragment matches); see docs/design.md for more.
func (g *generator) convertInlineFragment(
	namePrefix *prefixList,
	fragment *ast.InlineFragment,
	containingTypedef *ast.Definition,
	queryOptions *genqlientDirective,
) ([]*goStructField, error) {
	// You might think fragmentTypedef is just fragment.ObjectDefinition, but
	// actually that's the type into which the fragment is spread.
	fragmentTypedef := g.schema.Types[fragment.TypeCondition]
	if !fragmentMatches(containingTypedef, fragmentTypedef) {
		return nil, nil
	}
	return g.convertSelectionSet(namePrefix, fragment.SelectionSet,
		containingTypedef, queryOptions)
}

// convertFragmentSpread converts a single GraphQL fragment-spread
// (`...MyFragment`) into a Go struct-field.  If the fragment does not apply to
// this type, returns nil.
//
// containingTypedef is as described in convertInlineFragment, above.
func (g *generator) convertFragmentSpread(
	fragmentSpread *ast.FragmentSpread,
	containingTypedef *ast.Definition,
) (*goStructField, error) {
	if !fragmentMatches(containingTypedef, fragmentSpread.Definition.Definition) {
		return nil, nil
	}

	typ, ok := g.typeMap[fragmentSpread.Name]
	if !ok {
		// If we haven't yet, convert the fragment itself.  Note that fragments
		// aren't allowed to have cycles, so this won't recurse forever.
		var err error
		typ, err = g.convertNamedFragment(fragmentSpread.Definition)
		if err != nil {
			return nil, err
		}
	}

	iface, ok := typ.(*goInterfaceType)
	if ok && containingTypedef.Kind == ast.Object {
		// If the containing type is concrete, and the fragment spread is
		// abstract, refer directly to the appropriate implementation, to save
		// the caller having to do type-assertions that will always succeed.
		//
		// That is, if you do
		//	fragment F on I { ... }
		//  query Q { a { ...F } }
		// for the fragment we generate
		//  type F interface { ... }
		//  type FA struct { ... }
		//  // (other implementations)
		// when you spread F into a context of type A, we embed FA, not F.
		for _, impl := range iface.Implementations {
			if impl.GraphQLName == containingTypedef.Name {
				typ = impl
			}
		}
	}

	// TODO(benkraft): Set directive here if we ever allow @genqlient
	// directives on fragment-spreads.
	return &goStructField{GoName: "" /* i.e. embedded */, GoType: typ}, nil
}

// convertNamedFragment converts a single GraphQL named fragment-definition
// (`fragment MyFragment on MyType { ... }`) into a Go struct.
func (g *generator) convertNamedFragment(fragment *ast.FragmentDefinition) (goType, error) {
	typ := g.schema.Types[fragment.TypeCondition]

	comment, directive, err := g.parsePrecedingComment(fragment, nil, fragment.Position, nil)
	if err != nil {
		return nil, err
	}

	desc := descriptionInfo{
		CommentOverride:    comment,
		GraphQLName:        typ.Name,
		GraphQLDescription: typ.Description,
		FragmentName:       fragment.Name,
	}

	// The rest basically follows how we convert a definition, except that
	// things like type-names are a bit different.

	fields, err := g.convertSelectionSet(
		newPrefixList(fragment.Name), fragment.SelectionSet, typ, directive)
	if err != nil {
		return nil, err
	}
	if directive.GetFlatten() {
		// Flatten on a fragment-definition is a bit weird -- it makes one
		// fragment effectively an alias for another -- but no reason we can't
		// allow it.
		i, err := validateFlattenOption(typ, fragment.SelectionSet, fragment.Position)
		if err == nil {
			return fields[i].GoType, nil
		}
	}

	switch typ.Kind {
	case ast.Object:
		goType := &goStructType{
			GoName:          fragment.Name,
			Fields:          fields,
			Selection:       fragment.SelectionSet,
			descriptionInfo: desc,
			Generator:       g,
		}
		g.typeMap[fragment.Name] = goType
		return goType, nil
	case ast.Interface, ast.Union:
		implementationTypes := g.schema.GetPossibleTypes(typ)
		// Make sure we generate stable output by sorting the types by name when we get them
		sort.Slice(implementationTypes, func(i, j int) bool { return implementationTypes[i].Name < implementationTypes[j].Name })
		goType := &goInterfaceType{
			GoName:          fragment.Name,
			SharedFields:    fields,
			Implementations: make([]*goStructType, len(implementationTypes)),
			Selection:       fragment.SelectionSet,
			descriptionInfo: desc,
		}
		g.typeMap[fragment.Name] = goType

		for i, implDef := range implementationTypes {
			implFields, err := g.convertSelectionSet(
				newPrefixList(fragment.Name), fragment.SelectionSet, implDef, directive)
			if err != nil {
				return nil, err
			}

			implDesc := desc
			implDesc.GraphQLName = implDef.Name

			implTyp := &goStructType{
				GoName:          fragment.Name + upperFirst(implDef.Name),
				Fields:          implFields,
				Selection:       fragment.SelectionSet,
				descriptionInfo: implDesc,
				Generator:       g,
			}
			goType.Implementations[i] = implTyp
			g.typeMap[implTyp.GoName] = implTyp
		}

		return goType, nil
	default:
		return nil, errorf(fragment.Position, "invalid type for fragment: %v is a %v",
			fragment.TypeCondition, typ.Kind)
	}
}

// convertField converts a single GraphQL operation-field into a Go
// struct-field (and its type).
//
// Note that input-type fields are handled separately (inline in
// convertDefinition), because they come from the type-definition, not the
// operation.
func (g *generator) convertField(
	namePrefix *prefixList,
	field *ast.Field,
	fieldOptions, queryOptions *genqlientDirective,
) (*goStructField, error) {
	if field.Definition == nil {
		// Unclear why gqlparser hasn't already rejected this,
		// but empirically it might not.
		return nil, errorf(
			field.Position, "undefined field %v", field.Alias)
	}

	goName := upperFirst(field.Alias)
	namePrefix = nextPrefix(namePrefix, field)

	fieldGoType, err := g.convertType(
		namePrefix, field.Definition.Type, field.SelectionSet,
		fieldOptions, queryOptions)
	if err != nil {
		return nil, err
	}

	return &goStructField{
		GoName:      goName,
		GoType:      fieldGoType,
		JSONName:    field.Alias,
		GraphQLName: field.Name,
		Description: field.Definition.Description,
	}, nil
}
