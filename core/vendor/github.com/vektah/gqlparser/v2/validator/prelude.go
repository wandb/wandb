package validator

import (
	_ "embed"

	"github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/parser"
)

//go:generate go run ./internal/preludegen

//go:embed imported/prelude.graphql
var preludeGraphql string

// Prelude is the GraphQL source of the types and directives the spec declares
// implicitly. gqlparser.LoadSchema adds it ahead of the caller's sources.
var Prelude = &ast.Source{
	Name:    "prelude.graphql",
	Input:   preludeGraphql,
	BuiltIn: true,
}

// PreludeDocument returns the parsed Prelude: the built-in scalars, directives and
// introspection types that LoadSchema adds to every schema. Use it to find out what
// this version of gqlparser declares, instead of keeping a copy of those names.
//
// Each call parses Prelude again, so the caller owns the result and may modify it.
// It panics if the embedded prelude does not parse, which is a gqlparser bug.
func PreludeDocument() *ast.SchemaDocument {
	return mustParsePrelude(Prelude)
}

// mustParsePrelude parses prelude and panics if it does not parse. The embedded
// prelude always parses, so the panic only fires if gqlparser ships a broken one.
func mustParsePrelude(prelude *ast.Source) *ast.SchemaDocument {
	doc, err := parser.ParseSchema(prelude)
	if err != nil {
		panic("gqlparser: embedded prelude does not parse: " + err.Error())
	}
	return doc
}

// QueryIntrospectionFields returns the __schema and __type fields that the spec
// adds to the query root type. ValidateSchemaDocument appends them to the query
// type it finds; a caller that supplies its own query type needs them too.
//
// Each call returns new definitions, so the caller owns the result.
func QueryIntrospectionFields() ast.FieldList {
	return ast.FieldList{
		{
			Name: "__schema",
			Type: ast.NonNullNamedType("__Schema", nil),
		},
		{
			Name: "__type",
			Type: ast.NamedType("__Type", nil),
			Arguments: ast.ArgumentDefinitionList{
				{Name: "name", Type: ast.NonNullNamedType("String", nil)},
			},
		},
	}
}
