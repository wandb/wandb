package generate

// This file generates the names for genqlient's generated types.  This is
// somewhat tricky because the names need to be unique, stable, and, to the
// extent possible, human-readable and -writable.  See docs/design.md for an
// overview of the considerations; in short, we need long names.
//
// Specifically, the names we generate are of the form:
//	MyOperationMyFieldMyTypeMySubFieldMySubType
// We need the "MyOperation" prefix because different operations may have
// different fields selected in the same "location" within the query.  We need
// to include the field-path, because even within the same query, the same
// GraphQL type may have different selections in different locations.
// Including the types along the path is only strictly necessary in the case of
// interfaces, where, in a query like
//	query Q {
//		f {  # type: I
//			... on T { g { h } }
//			... on U { g { h } }
//		}
//	}
// the type of <response>.f.g may be different depending on whether the
// concrete type is a T or a U; if we simply called the types QFG they'd
// collide.  We could in principle omit the types where there are no interfaces
// in sight, but having the last thing in the name be the actual GraphQL type
// name (MySubType in the first example) makes things more readable, and the
// value of consistency seems greater than the value of brevity, given the
// types are quite verbose either way.  Note that in all cases the "MyField" is
// the alias of the field -- the name it has in this query -- since you could
// have `query Q { a: f { b }, c: f { d } }` and Q.A and Q.C must have
// different types.
//
// One subtlety in the above description is: is the "MyType" the interface or
// the implementation?  When it's a suffix, the answer is both: we generate
// both MyFieldMyInterface and MyFieldMyImplementation, and the latter, in Go,
// implements the former.  (See docs/design.md for more.)  But as an infix, we
// use the type on which the field is requested.  Concretely, the following
// schema and query:
//	type Query { f: I }
//	interface I { g: G }
//	type T implements I { g: G, h: H }
//	type U implements I { g: G, h: H }
//	type G { g1: String, g2: String }
//	type H { h1: String, h2: String, h3: String, h4: String }
//
//	query Q {
//		f {
//			g { g1 g2 }
//			... on T { h { h1 h2 } }
//			... on U { h { h3 h4 } }
//		}
//	}
// The field g must have type QFIG (not QFTG and QFHG), so that QFI's method
// GetG() can return a consistent type.  But the fields h must have types QFTH
// and QFUH (not QFIH), because the two are different: the former has fields h1
// and h2, whereas the latter has fields h3 and h4.  So, in summary, since `g`
// is selected in a context of type I, it uses that (interface) type in its
// type-name, and `h` is selected in contexts of types T and U, they use those
// (implementation) types in their type-names.
//
// We do shorten the names in one case: if the name of a field ends with
// the name of its type, we omit the type name, avoiding types like
// MyQueryUserUser when querying a field of type user and value user.  Note we
// do not do this for field names, both because it's less common, and because
// in `query Q { user { user { id } } }` we do need both QUser and QUserUser --
// they have different fields.
//
// Note that there are a few potential collisions from this algorithm:
// - When generating Go types for GraphQL interface types, we generate both
//   ...MyFieldMyInterfaceType and ...MyFieldMyImplType.  If an interface's
//   name is a suffix of its implementation's name, and both are suffixes of a
//   field of that type, we'll shorten both, resulting in a collision.
// - Names of different casing (e.g. fields `myField` and `MyField`) can
//   collide (the first is standard usage but both are legal).
// - We don't put a special character between parts, so fields like
//		query Q {
//			ab { ... }  # type: C
//			abc { ... } # type: C
//			a { ... }   # type: BC
//		}
//   can collide.
// All cases seem fairly rare in practice; eventually we'll likely allow users
// the ability to specify their own names, which they could use to avoid this
// (see [issue #12]).
// TODO(benkraft): We should probably at least try to detect it and bail.
//
// [issue #12]: https://github.com/Khan/genqlient/issues/12
//
// To implement all of the above, as we traverse the operation (and schema) in
// convert.go, we keep track of a list of parts to prefix to our type-names.
// The list always ends with a field, not a type; and we extend it when
// traversing fields, to allow for correct handling of the interface case
// discussed above.  This file implements the actual maintenance of that
// prefix, and the code to compute the actual type-name from it.
//
// Note that input objects and enums are handled separately (inline in
// convertDefinition) since the same considerations don't apply and their names
// are thus quite simple.  We also specially-handle the type of the toplevel
// response object (inline in convertOperation).

import (
	"fmt"
	"strings"

	"github.com/vektah/gqlparser/v2/ast"
)

// Yes, a linked list!  Of name-prefixes in *reverse* order, i.e. from end to
// start.
//
// We could use a stack -- it would probably be marginally
// more efficient -- but then the caller would have to know more about how to
// manage it safely.  Using a list, and treating it as immutable, makes it
// easy.
type prefixList struct {
	head string // the list goes back-to-front, so this is the *last* prefix
	tail *prefixList
}

// creates a new one-element list
func newPrefixList(item string) *prefixList {
	return &prefixList{head: item}
}

func joinPrefixList(prefix *prefixList) string {
	var reversed []string
	for ; prefix != nil; prefix = prefix.tail {
		reversed = append(reversed, prefix.head)
	}
	l := len(reversed)
	for i := 0; i < l/2; i++ {
		reversed[i], reversed[l-1-i] = reversed[l-1-i], reversed[i]
	}
	return strings.Join(reversed, "")
}

// Given a prefix-list, and the next type-name, compute the prefix-list with
// that type-name added (if applicable).  The returned value is not a valid
// prefix-list, since it ends with a type, not a field (see top-of-file
// comment), but it's used to construct both the type-names from the input and
// the next prefix-list.
func typeNameParts(prefix *prefixList, typeName string) *prefixList {
	// GraphQL types are conventionally UpperCamelCase, but it's not required;
	// our names will look best if they are.
	typeName = upperFirst(typeName)
	// If the prefix has just one part, that's the operation-name.  There's no
	// need to add "Query" or "Mutation".  (Zero should never happen.)
	if prefix == nil || prefix.tail == nil ||
		// If the name-so-far ends with this type's name, omit the
		// type-name (see the "shortened" case in the top-of-file comment).
		strings.HasSuffix(joinPrefixList(prefix), typeName) {
		return prefix
	}
	return &prefixList{typeName, prefix}
}

// Given a prefix-list, and a field, compute the next prefix-list, which will
// be used for that field's selections.
func nextPrefix(prefix *prefixList, field *ast.Field) *prefixList {
	// Add the type.
	prefix = typeNameParts(prefix, field.ObjectDefinition.Name)
	// Add the field (there's no shortening here, see top-of-file comment).
	prefix = &prefixList{upperFirst(field.Alias), prefix}
	return prefix
}

// Given a prefix-list, and the GraphQL of the current type, compute the name
// we should give it in Go.
func makeTypeName(prefix *prefixList, typeName string) string {
	return joinPrefixList(typeNameParts(prefix, typeName))
}

// Like makeTypeName, but append typeName unconditionally.
//
// This is used for when you specify a type-name for a field of interface
// type; we use YourName for the interface, but need to do YourNameImplName for
// the implementations.
func makeLongTypeName(prefix *prefixList, typeName string) string {
	typeName = upperFirst(typeName)
	return joinPrefixList(&prefixList{typeName, prefix})
}

func (casing *Casing) enumValueName(goTypeName string, enum *ast.Definition, val *ast.EnumValueDefinition) string {
	switch algo := casing.forEnum(enum.Name); algo {
	case CasingDefault:
		return goTypeName + goConstName(val.Name)
	case CasingRaw:
		return goTypeName + "_" + val.Name
	default:
		// Should already be caught by validation.
		panic(fmt.Sprintf("unknown casing algorithm %s", algo))
	}
}
