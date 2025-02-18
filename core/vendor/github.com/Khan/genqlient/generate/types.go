package generate

// This file defines the data structures from which genqlient generates types,
// and the code to write them out as actual Go code.  The main entrypoint is
// goType, which represents such a type, but convert.go also constructs each
// of the implementing types, by traversing the GraphQL operation and schema.

import (
	"fmt"
	"io"
	"strings"

	"github.com/vektah/gqlparser/v2/ast"
)

// goType represents a type for which we'll generate code.
type goType interface {
	// WriteDefinition writes the code for this type into the given io.Writer.
	//
	// TODO(benkraft): Some of the implementations might now benefit from being
	// converted to templates.
	WriteDefinition(io.Writer, *generator) error

	// Reference returns the Go name of this type, e.g. []*MyStruct, and may be
	// used to refer to it in Go code.
	Reference() string

	// GraphQLTypeName returns the name of the GraphQL type to which this Go type
	// corresponds.
	GraphQLTypeName() string

	// SelectionSet returns the selection-set of the GraphQL field from which
	// this type was generated, or nil if none is applicable (for GraphQL
	// scalar, enum, and input types, as well as any opaque
	// (non-genqlient-generated) type since those are validated upon creation).
	SelectionSet() ast.SelectionSet

	// Remove slice/pointer wrappers, and return the underlying (named (or
	// builtin)) type.  For example, given []*MyStruct, return MyStruct.
	Unwrap() goType

	// Count the number of times Unwrap() will unwrap a slice type.  For
	// example, given [][][]*MyStruct (or []**[][]*MyStruct, but we never
	// currently generate that), return 3.
	SliceDepth() int

	// True if Unwrap() will unwrap a pointer at least once.
	IsPointer() bool
}

var (
	_ goType = (*goOpaqueType)(nil)
	_ goType = (*goSliceType)(nil)
	_ goType = (*goPointerType)(nil)
	_ goType = (*goEnumType)(nil)
	_ goType = (*goStructType)(nil)
	_ goType = (*goInterfaceType)(nil)
	_ goType = (*goGenericType)(nil)
)

type (
	// goOpaqueType represents a user-defined or builtin type, often used to
	// represent a GraphQL scalar.  (See Config.Bindings for more context.)
	goOpaqueType struct {
		GoRef                  string
		GraphQLName            string
		Marshaler, Unmarshaler string
	}
	// goTypenameForBuiltinType represents a builtin type that was
	// given a different name due to a `typename` directive.  We
	// create a type like `type MyString string` for it.
	goTypenameForBuiltinType struct {
		GoTypeName    string
		GoBuiltinName string
		GraphQLName   string
	}
	// goSliceType represents the Go type []Elem, used to represent GraphQL
	// list types.
	goSliceType struct{ Elem goType }
	// goSliceType represents the Go type *Elem, used when requested by the
	// user (perhaps to handle nulls explicitly, or to avoid copying large
	// structures).
	goPointerType struct{ Elem goType }
	// goGenericType represent the Go type GoGenericRef[Elem], used when requested by the
	// user to box nullable data without using pointers or sentinel values
	goGenericType struct {
		GoGenericRef string
		Elem         goType
	}
)

// Opaque types are defined by the user; pointers and slices need no definition
func (typ *goOpaqueType) WriteDefinition(io.Writer, *generator) error { return nil }

func (typ *goTypenameForBuiltinType) WriteDefinition(w io.Writer, g *generator) error {
	fmt.Fprintf(w, "type %s %s", typ.GoTypeName, typ.GoBuiltinName)
	return nil
}
func (typ *goSliceType) WriteDefinition(io.Writer, *generator) error   { return nil }
func (typ *goPointerType) WriteDefinition(io.Writer, *generator) error { return nil }
func (typ *goGenericType) WriteDefinition(io.Writer, *generator) error { return nil }

func (typ *goOpaqueType) Reference() string             { return typ.GoRef }
func (typ *goTypenameForBuiltinType) Reference() string { return typ.GoTypeName }
func (typ *goSliceType) Reference() string              { return "[]" + typ.Elem.Reference() }
func (typ *goPointerType) Reference() string            { return "*" + typ.Elem.Reference() }
func (typ *goGenericType) Reference() string {
	return fmt.Sprintf("%s[%s]", typ.GoGenericRef, typ.Elem.Reference())
}

func (typ *goOpaqueType) SelectionSet() ast.SelectionSet             { return nil }
func (typ *goTypenameForBuiltinType) SelectionSet() ast.SelectionSet { return nil }
func (typ *goSliceType) SelectionSet() ast.SelectionSet              { return typ.Elem.SelectionSet() }
func (typ *goPointerType) SelectionSet() ast.SelectionSet            { return typ.Elem.SelectionSet() }
func (typ *goGenericType) SelectionSet() ast.SelectionSet            { return typ.Elem.SelectionSet() }

func (typ *goOpaqueType) GraphQLTypeName() string             { return typ.GraphQLName }
func (typ *goTypenameForBuiltinType) GraphQLTypeName() string { return typ.GraphQLName }
func (typ *goSliceType) GraphQLTypeName() string              { return typ.Elem.GraphQLTypeName() }
func (typ *goPointerType) GraphQLTypeName() string            { return typ.Elem.GraphQLTypeName() }
func (typ *goGenericType) GraphQLTypeName() string            { return typ.Elem.GraphQLTypeName() }

// goEnumType represents a Go named-string type used to represent a GraphQL
// enum.  In this case, we generate both the type (`type T string`) and also a
// list of consts representing the values.
type goEnumType struct {
	GoName      string
	GraphQLName string
	Description string
	Values      []goEnumValue
}

type goEnumValue struct {
	GoName      string
	GraphQLName string
	Description string
}

func (typ *goEnumType) WriteDefinition(w io.Writer, g *generator) error {
	// All GraphQL enums have underlying type string (in the Go sense).
	writeDescription(w, typ.Description)
	fmt.Fprintf(w, "type %s string\n", typ.GoName)
	fmt.Fprintf(w, "const (\n")
	for _, val := range typ.Values {
		writeDescription(w, val.Description)
		fmt.Fprintf(w, "%s %s = \"%s\"\n",
			val.GoName, typ.GoName, val.GraphQLName)
	}
	fmt.Fprintf(w, ")\n")
	return nil
}

func (typ *goEnumType) Reference() string              { return typ.GoName }
func (typ *goEnumType) SelectionSet() ast.SelectionSet { return nil }
func (typ *goEnumType) GraphQLTypeName() string        { return typ.GraphQLName }

// goStructType represents a Go struct type used to represent a GraphQL object
// or input-object type.
type goStructType struct {
	GoName    string
	Fields    []*goStructField
	IsInput   bool
	Selection ast.SelectionSet
	descriptionInfo
	Generator *generator // for the convenience of the template
}

type goStructField struct {
	GoName      string
	GoType      goType
	JSONName    string // i.e. the field's alias in this query
	GraphQLName string // i.e. the field's name in its type-def
	Omitempty   bool   // only used on input types
	Description string
}

// IsAbstract returns true if this field is of abstract type (i.e. GraphQL
// union or interface; equivalently, represented by an interface in Go).
func (field *goStructField) IsAbstract() bool {
	_, ok := field.GoType.Unwrap().(*goInterfaceType)
	return ok
}

// IsEmbedded returns true if this field is embedded (a.k.a. anonymous), which
// is in practice true if it corresponds to a named fragment spread in GraphQL.
func (field *goStructField) IsEmbedded() bool {
	return field.GoName == ""
}

// Selector returns the field's name, which is unqualified type-name if it's
// embedded.
func (field *goStructField) Selector() string {
	if field.GoName != "" {
		return field.GoName
	}
	// TODO(benkraft): This assumes the type is package-local, which is always
	// true for embedded types for us, but isn't the most robust assumption.
	return field.GoType.Unwrap().Reference()
}

// unmarshaler returns:
//   - the name of the function to use to unmarshal this field
//   - true if this is a fully-qualified name (false if it is a package-local
//     unqualified name)
//   - true if we need to generate an unmarshaler at all, false if the default
//     behavior will suffice
func (field *goStructField) unmarshaler() (qualifiedName string, needsImport bool, needsUnmarshaler bool) {
	switch typ := field.GoType.Unwrap().(type) {
	case *goOpaqueType:
		if typ.Unmarshaler != "" {
			return typ.Unmarshaler, true, true
		}
	case *goInterfaceType:
		return "__unmarshal" + typ.Reference(), false, true
	}
	return "encoding/json.Unmarshal", true, field.IsEmbedded()
}

// Unmarshaler returns the Go name of the function to use to unmarshal this
// field (which may be "json.Unmarshal" if there's not a special one).
func (field *goStructField) Unmarshaler(g *generator) (string, error) {
	name, needsImport, _ := field.unmarshaler()
	if needsImport {
		return g.ref(name)
	}
	return name, nil
}

// marshaler returns:
//   - the fully-qualified name of the function to use to marshal this field
//   - true if we need to generate an marshaler at all, false if the default
//     behavior will suffice
func (field *goStructField) marshaler() (qualifiedName string, needsImport bool, needsMarshaler bool) {
	switch typ := field.GoType.Unwrap().(type) {
	case *goOpaqueType:
		if typ.Marshaler != "" {
			return typ.Marshaler, true, true
		}
	case *goInterfaceType:
		return "__marshal" + typ.Reference(), false, true
	}
	return "encoding/json.Marshal", true, field.IsEmbedded()
}

// Marshaler returns the Go name of the function to use to marshal this
// field (which may be "json.Marshal" if there's not a special one).
func (field *goStructField) Marshaler(g *generator) (string, error) {
	name, needsImport, _ := field.marshaler()
	if needsImport {
		return g.ref(name)
	}
	return name, nil
}

// NeedsMarshaling returns true if this field needs special handling when
// marshaling and unmarshaling, e.g. if it has a user-specified custom
// (un)marshaler.  Note if it needs one, it needs the other: even if the user
// only specified an unmarshaler, we need to add `json:"-"` to the field, which
// means we need to specially handling it when marshaling.
func (field *goStructField) NeedsMarshaling() bool {
	_, _, ok1 := field.marshaler()
	_, _, ok2 := field.unmarshaler()
	return ok1 || ok2
}

// NeedsMarshaler returns true if any fields of this type need special
// handling when (un)marshaling (see goStructField.NeedsMarshaling).
func (typ *goStructType) NeedsMarshaling() bool {
	for _, f := range typ.Fields {
		if f.NeedsMarshaling() {
			return true
		}
	}
	return false
}

// selector represents a field and the path to get there from the type in
// question, and is used in FlattenedFields, below.
type selector struct {
	*goStructField
	// e.g. "OuterEmbed.InnerEmbed.LeafField"
	Selector string
}

// FlattenedFields returns the fields of this type and its recursive embeds,
// and the paths to reach them (via those embeds), but with different
// visibility rules for conflicting fields than Go.
//
// (Before you read further, now's a good time to review [Go's rules].
// Done?  Good.)
//
// To illustrate the need, consider the following query:
//
//	fragment A on T { id }
//	fragment B on T { id }
//	query Q { t { ...A ...B } }
//
// We generate types:
//
//	type A struct { Id string `json:"id"` }
//	type B struct { Id string `json:"id"` }
//	type QT struct { A; B }
//
// According to Go's embedding rules, QT has no field Id: since QT.A.Id and
// QT.B.Id are at equal depth, neither wins and gets promoted.  (Go's JSON
// library uses similar logic to decide which field to write to JSON, except
// with the additional rule that a field with a JSON tag wins over a field
// without; in our case both have such a field.)
//
// Those rules don't work for us.  When unmarshaling, we want to fill in all
// the potentially-matching fields (QT.A.Id and QT.B.Id in this case), and when
// marshaling, we want to always marshal exactly one potentially-conflicting
// field; we're happy to use the Go visibility rules when they apply but we
// need to always marshal one field, even if there's not a clear best choice.
// For unmarshaling, our QT.UnmarshalJSON ends up unmarshaling the same JSON
// object into QT, QT.A, and QT.B, which gives us the behavior we want.  But
// for marshaling, we need to resolve the conflicts: if we simply marshaled QT,
// QT.A, and QT.B, we'd have to do some JSON-surgery to join them, and we'd
// probably end up with duplicate fields, which leads to unpredictable behavior
// based on the reader.  That's no good.
//
// So: instead, we have our own rules, which work like the Go rules, except
// that if there's a tie we choose the first field (in source order).  (In
// practice, hopefully, they all match, but validating that is even more work
// for a fairly rare case.)  This function returns, for each JSON-name, the Go
// field we want to use.  In the example above, it would return:
//
//	[]selector{{<goStructField for QT.A.Id>, "A.Id"}}
//
// [Go's rules]: https://golang.org/ref/spec#Selectors
func (typ *goStructType) FlattenedFields() ([]*selector, error) {
	seenJSONNames := map[string]bool{}
	retval := make([]*selector, 0, len(typ.Fields))

	queue := make([]*selector, len(typ.Fields))
	for i, field := range typ.Fields {
		queue[i] = &selector{field, field.Selector()}
	}

	// Since our (non-embedded) fields always have JSON tags, the logic we want
	// is simply: do a breadth-first search through the recursively embedded
	// fields, and take the first one we see with a given JSON tag.
	for len(queue) > 0 {
		field := queue[0]
		queue = queue[1:]
		if field.IsEmbedded() {
			typ, ok := field.GoType.(*goStructType)
			if !ok {
				// Should never happen: embeds correspond to named fragments,
				// and even if the fragment is of interface type in GraphQL,
				// either it's spread into a concrete type, or we are writing
				// one of the implementations of the interface into which it's
				// spread; either way we embed the corresponding implementation
				// of the fragment.
				return nil, errorf(nil,
					"genqlient internal error: embedded field %s.%s was not a struct",
					typ.GoName, field.GoName)
			}

			// Enqueue the embedded fields for our BFS.
			for _, subField := range typ.Fields {
				queue = append(queue,
					&selector{subField, field.Selector + "." + subField.Selector()})
			}
			continue
		}

		if seenJSONNames[field.JSONName] {
			// We already chose a selector for this JSON field.  Skip it.
			continue
		}

		// Else, we are the selector we are looking for.
		seenJSONNames[field.JSONName] = true
		retval = append(retval, field)
	}
	return retval, nil
}

func (typ *goStructType) WriteDefinition(w io.Writer, g *generator) error {
	writeDescription(w, structDescription(typ))

	fmt.Fprintf(w, "type %s struct {\n", typ.GoName)
	for _, field := range typ.Fields {
		writeDescription(w, field.Description)
		jsonTag := `"` + field.JSONName
		if field.Omitempty {
			jsonTag += ",omitempty"
		}
		jsonTag += `"`
		if field.NeedsMarshaling() {
			// certain types are handled in our (Un)MarshalJSON (see below)
			jsonTag = `"-"`
		}
		// Note for embedded types field.GoName is "", which produces the code
		// we want!
		fmt.Fprintf(w, "\t%s %s `json:%s`\n",
			field.GoName, field.GoType.Reference(), jsonTag)
	}
	fmt.Fprintf(w, "}\n")

	// Write out getter methods for each field.  These are most useful for
	// shared fields of an interface -- the methods will be included in the
	// interface.  But they can be useful in other cases, for example where you
	// have a union several of whose members have a shared field (and can
	// thereby be handled together).  For simplicity's sake, we just write the
	// methods always.
	//
	// Note we use the *flattened* fields here, which ensures we avoid
	// conflicts in the case where multiple embedded types include the same
	// field.
	flattened, err := typ.FlattenedFields()
	if err != nil {
		return err
	}
	for _, field := range flattened {
		description := fmt.Sprintf(
			"Get%s returns %s.%s, and is useful for accessing the field via an interface.",
			field.GoName, typ.GoName, field.GoName)
		writeDescription(w, description)
		fmt.Fprintf(w, "func (v *%s) Get%s() %s { return v.%s }\n",
			typ.GoName, field.GoName, field.GoType.Reference(), field.Selector)
	}

	// Now, if needed, write the marshaler/unmarshaler.  We need one if we have
	// any interface-typed fields, or any embedded fields.
	//
	// For interface-typed fields, ideally we'd write an UnmarshalJSON method
	// on the field, but you can't add a method to an interface.  So we write a
	// per-interface-type helper, but we have to call it (with a little
	// boilerplate) everywhere the type is referenced.
	//
	// For embedded fields (from fragments), mostly the JSON library would just
	// do what we want, but there are two problems.  First, if the embedded
	// type has its own UnmarshalJSON, naively that would be promoted to
	// become our UnmarshalJSON, which is no good.  But we don't want to just
	// hide that method and inline its fields, either; we need to call its
	// UnmarshalJSON (on the same object we unmarshal into this struct).
	// Second, if the embedded type duplicates any fields of the embedding type
	// -- maybe both the fragment and the selection into which it's spread
	// select the same field, or several fragments select the same field -- the
	// JSON library will only fill one of those (the least-nested one); we want
	// to fill them all.
	//
	// For fields with a custom marshaler or unmarshaler, we do basically the
	// same thing as interface-typed fields, except the user has defined the
	// helper.
	//
	// Note that genqlient itself only uses unmarshalers for output types, and
	// marshalers for input types.  But we write both in case you want to write
	// your data to JSON for some reason (say to put it in a cache).  (And we
	// need to write both if we need to write either, because in such cases we
	// write a `json:"-"` tag on the field.)
	//
	// TODO(benkraft): If/when proposal #5901 is implemented (Go 1.18 at the
	// earliest), we may be able to do some of this a simpler way.
	if typ.NeedsMarshaling() {
		err := g.render("unmarshal.go.tmpl", w, typ)
		if err != nil {
			return err
		}
		err = g.render("marshal.go.tmpl", w, typ)
		if err != nil {
			return err
		}
	}
	return nil
}

func (typ *goStructType) Reference() string              { return typ.GoName }
func (typ *goStructType) SelectionSet() ast.SelectionSet { return typ.Selection }
func (typ *goStructType) GraphQLTypeName() string        { return typ.GraphQLName }

// goInterfaceType represents a Go interface type, used to represent a GraphQL
// interface or union type.
type goInterfaceType struct {
	GoName string
	// Fields shared by all the interface's implementations;
	// we'll generate getter methods for each.
	SharedFields    []*goStructField
	Implementations []*goStructType
	Selection       ast.SelectionSet
	descriptionInfo
}

func (typ *goInterfaceType) WriteDefinition(w io.Writer, g *generator) error {
	writeDescription(w, interfaceDescription(typ))

	// Write the interface.
	fmt.Fprintf(w, "type %s interface {\n", typ.GoName)
	implementsMethodName := fmt.Sprintf("implementsGraphQLInterface%v", typ.GoName)
	fmt.Fprintf(w, "\t%s()\n", implementsMethodName)
	for _, sharedField := range typ.SharedFields {
		if sharedField.GoName == "" { // embedded type
			fmt.Fprintf(w, "\t%s\n", sharedField.GoType.Reference())
			continue
		}

		methodName := "Get" + sharedField.GoName
		description := ""
		if sharedField.GraphQLName == "__typename" {
			description = fmt.Sprintf(
				"%s returns the receiver's concrete GraphQL type-name "+
					"(see interface doc for possible values).", methodName)
		} else {
			description = fmt.Sprintf(
				`%s returns the interface-field %q from its implementation.`,
				methodName, sharedField.GraphQLName)
			if sharedField.Description != "" {
				description = fmt.Sprintf(
					"%s\nThe GraphQL interface field's documentation follows.\n\n%s",
					description, sharedField.Description)
			}
		}

		writeDescription(w, description)
		fmt.Fprintf(w, "\t%s() %s\n", methodName, sharedField.GoType.Reference())
	}
	fmt.Fprintf(w, "}\n")

	// Now, write out the implementations.
	for _, impl := range typ.Implementations {
		fmt.Fprintf(w, "func (v *%s) %s() {}\n",
			impl.Reference(), implementsMethodName)
	}

	// Finally, write the marshal- and unmarshal-helpers, which
	// will be called by struct fields referencing this type (see
	// goStructType.WriteDefinition).
	err := g.render("unmarshal_helper.go.tmpl", w, typ)
	if err != nil {
		return err
	}
	return g.render("marshal_helper.go.tmpl", w, typ)
}

func (typ *goInterfaceType) Reference() string              { return typ.GoName }
func (typ *goInterfaceType) SelectionSet() ast.SelectionSet { return typ.Selection }
func (typ *goInterfaceType) GraphQLTypeName() string        { return typ.GraphQLName }

func (typ *goOpaqueType) Unwrap() goType             { return typ }
func (typ *goTypenameForBuiltinType) Unwrap() goType { return typ }
func (typ *goSliceType) Unwrap() goType              { return typ.Elem.Unwrap() }
func (typ *goPointerType) Unwrap() goType            { return typ.Elem.Unwrap() }
func (typ *goGenericType) Unwrap() goType            { return typ.Elem.Unwrap() }
func (typ *goEnumType) Unwrap() goType               { return typ }
func (typ *goStructType) Unwrap() goType             { return typ }
func (typ *goInterfaceType) Unwrap() goType          { return typ }

func (typ *goOpaqueType) SliceDepth() int             { return 0 }
func (typ *goTypenameForBuiltinType) SliceDepth() int { return 0 }
func (typ *goSliceType) SliceDepth() int              { return typ.Elem.SliceDepth() + 1 }
func (typ *goPointerType) SliceDepth() int            { return 0 }
func (typ *goGenericType) SliceDepth() int            { return 0 }
func (typ *goEnumType) SliceDepth() int               { return 0 }
func (typ *goStructType) SliceDepth() int             { return 0 }
func (typ *goInterfaceType) SliceDepth() int          { return 0 }

func (typ *goOpaqueType) IsPointer() bool             { return false }
func (typ *goTypenameForBuiltinType) IsPointer() bool { return false }
func (typ *goSliceType) IsPointer() bool              { return typ.Elem.IsPointer() }
func (typ *goPointerType) IsPointer() bool            { return true }
func (typ *goGenericType) IsPointer() bool            { return false }
func (typ *goEnumType) IsPointer() bool               { return false }
func (typ *goStructType) IsPointer() bool             { return false }
func (typ *goInterfaceType) IsPointer() bool          { return false }

func writeDescription(w io.Writer, desc string) {
	if desc != "" {
		for _, line := range strings.Split(desc, "\n") {
			fmt.Fprintf(w, "// %s\n", strings.TrimLeft(line, " \t"))
		}
	}
}
