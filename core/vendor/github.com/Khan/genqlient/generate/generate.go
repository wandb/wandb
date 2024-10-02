package generate

// This file implements the main entrypoint and framework for the genqlient
// code-generation process.  See comments in Generate for the high-level
// overview.

import (
	"bytes"
	"encoding/json"
	"go/format"
	"io"
	"sort"
	"strings"
	"text/template"

	"github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/formatter"
	"github.com/vektah/gqlparser/v2/validator"
	"golang.org/x/tools/imports"
)

// generator is the context for the codegen process (and ends up getting passed
// to the template).
type generator struct {
	// The config for which we are generating code.
	Config *Config
	// The list of operations for which to generate code.
	Operations []*operation
	// The types needed for these operations.
	typeMap map[string]goType
	// Imports needed for these operations, path -> alias and alias -> true
	imports     map[string]string
	usedAliases map[string]bool
	// True if we've already written out the imports (in which case they can't
	// be modified).
	importsLocked bool
	// Cache of loaded templates.
	templateCache map[string]*template.Template
	// Schema we are generating code against
	schema *ast.Schema
	// Named fragments (map by name), so we can look them up from spreads.
	// TODO(benkraft): In theory we shouldn't need this, we can just use
	// ast.FragmentSpread.Definition, but for some reason it doesn't seem to be
	// set consistently, even post-validation.
	fragments map[string]*ast.FragmentDefinition
}

// JSON tags in operation are for ExportOperations (see Config for details).
type operation struct {
	// The type of the operation (query, mutation, or subscription).
	Type ast.Operation `json:"-"`
	// The name of the operation, from GraphQL.
	Name string `json:"operationName"`
	// The documentation for the operation, from GraphQL.
	Doc string `json:"-"`
	// The body of the operation to send.
	Body string `json:"query"`
	// The type of the argument to the operation, which we use both internally
	// and to construct the arguments.  We do it this way so we can use the
	// machinery we have for handling (and, specifically, json-marshaling)
	// types.
	Input *goStructType `json:"-"`
	// The type-name for the operation's response type.
	ResponseName string `json:"-"`
	// The original filename from which we got this query.
	SourceFilename string `json:"sourceLocation"`
	// The config within which we are generating code.
	Config *Config `json:"-"`
}

type exportedOperations struct {
	Operations []*operation `json:"operations"`
}

func newGenerator(
	config *Config,
	schema *ast.Schema,
	fragments ast.FragmentDefinitionList,
) *generator {
	g := generator{
		Config:        config,
		typeMap:       map[string]goType{},
		imports:       map[string]string{},
		usedAliases:   map[string]bool{},
		templateCache: map[string]*template.Template{},
		schema:        schema,
		fragments:     make(map[string]*ast.FragmentDefinition, len(fragments)),
	}

	for _, fragment := range fragments {
		g.fragments[fragment.Name] = fragment
	}

	return &g
}

func (g *generator) WriteTypes(w io.Writer) error {
	names := make([]string, 0, len(g.typeMap))
	for name := range g.typeMap {
		names = append(names, name)
	}
	// Sort alphabetically by type-name.  Sorting somehow deterministically is
	// important to ensure generated code is deterministic.  Alphabetical is
	// nice because it's easy, and in the current naming scheme, it's even
	// vaguely aligned to the structure of the queries.
	sort.Strings(names)

	for _, name := range names {
		err := g.typeMap[name].WriteDefinition(w, g)
		if err != nil {
			return err
		}
		// Make sure we have blank lines between types (and between the last
		// type and the first operation)
		_, err = io.WriteString(w, "\n\n")
		if err != nil {
			return err
		}
	}
	return nil
}

// usedFragmentNames returns the named-fragments used by (i.e. spread into)
// this operation.
func (g *generator) usedFragments(op *ast.OperationDefinition) ast.FragmentDefinitionList {
	var retval, queue ast.FragmentDefinitionList
	seen := map[string]bool{}

	var observers validator.Events
	// Fragment-spreads are easy to find; just ask for them!
	observers.OnFragmentSpread(func(_ *validator.Walker, fragmentSpread *ast.FragmentSpread) {
		if seen[fragmentSpread.Name] {
			return
		}
		def := g.fragments[fragmentSpread.Name]
		seen[fragmentSpread.Name] = true
		retval = append(retval, def)
		queue = append(queue, def)
	})

	doc := ast.QueryDocument{Operations: ast.OperationList{op}}
	validator.Walk(g.schema, &doc, &observers)
	// Well, easy-ish: we also have to look recursively.
	// Note GraphQL guarantees there are no cycles among fragments:
	// https://spec.graphql.org/draft/#sec-Fragment-spreads-must-not-form-cycles
	for len(queue) > 0 {
		doc = ast.QueryDocument{Fragments: ast.FragmentDefinitionList{queue[0]}}
		validator.Walk(g.schema, &doc, &observers) // traversal is the same
		queue = queue[1:]
	}

	return retval
}

// Preprocess each query to make any changes that genqlient needs.
//
// At present, the only change is that we add __typename, if not already
// requested, to each field of interface type, so we can use the right types
// when unmarshaling.
func (g *generator) preprocessQueryDocument(doc *ast.QueryDocument) {
	var observers validator.Events
	// We want to ensure that everywhere you ask for some list of fields (a
	// selection-set) from an interface (or union) type, you ask for its
	// __typename field.  There are four places we might find a selection-set:
	// at the toplevel of a query, on a field, or in an inline or named
	// fragment.  The toplevel of a query must be an object type, so we don't
	// need to consider that.  And fragments must (if used at all) be spread
	// into some parent selection-set, so we'll add __typename there (if
	// needed).  Note this does mean abstract-typed fragments spread into
	// object-typed scope will *not* have access to `__typename`, but they
	// indeed don't need it, since we do know the type in that context.
	// TODO(benkraft): We should omit __typename if you asked for
	// `# @genqlient(struct: true)`.
	observers.OnField(func(_ *validator.Walker, field *ast.Field) {
		// We are interested in a field from the query like
		//	field { subField ... }
		// where the schema looks like
		//	type ... {       # or interface/union
		//		field: FieldType    # or [FieldType!]! etc.
		//	}
		//	interface FieldType {   # or union
		//		subField: ...
		//	}
		// If FieldType is an interface/union, and none of the subFields is
		// __typename, we want to change the query to
		//	field { __typename subField ... }

		fieldType := g.schema.Types[field.Definition.Type.Name()]
		if fieldType.Kind != ast.Interface && fieldType.Kind != ast.Union {
			return // a concrete type
		}

		hasTypename := false
		for _, selection := range field.SelectionSet {
			// Check if we already selected __typename. We ignore fragments,
			// because we want __typename as a toplevel field.
			subField, ok := selection.(*ast.Field)
			if ok && subField.Name == "__typename" {
				hasTypename = true
			}
		}
		if !hasTypename {
			// Ok, we need to add the field!
			field.SelectionSet = append(ast.SelectionSet{
				&ast.Field{
					Alias: "__typename", Name: "__typename",
					// Fake definition for the magic field __typename cribbed
					// from gqlparser's validator/walk.go, equivalent to
					//	__typename: String
					// TODO(benkraft): This should in principle be
					//	__typename: String!
					// But genqlient doesn't care, so we just match gqlparser.
					Definition: &ast.FieldDefinition{
						Name: "__typename",
						Type: ast.NamedType("String", nil /* pos */),
					},
					// Definition of the object that contains this field, i.e.
					// FieldType.
					ObjectDefinition: fieldType,
				},
			}, field.SelectionSet...)
		}
	})
	validator.Walk(g.schema, doc, &observers)
}

// validateOperation checks for a few classes of operations that gqlparser
// considers valid but we don't allow, and returns an error if this operation
// is invalid for genqlient's purposes.
func (g *generator) validateOperation(op *ast.OperationDefinition) error {
	_, err := g.baseTypeForOperation(op.Operation)
	if err != nil {
		// (e.g. operation has subscriptions, which we don't support)
		return err
	}

	if op.Name == "" {
		return errorf(op.Position, "operations must have operation-names")
	} else if goKeywords[op.Name] {
		return errorf(op.Position, "operation name must not be a go keyword")
	}

	return nil
}

// addOperation adds to g.Operations the information needed to generate a
// genqlient entrypoint function for the given operation.  It also adds to
// g.typeMap any types referenced by the operation, except for types belonging
// to named fragments, which are added separately by Generate via
// convertFragment.
func (g *generator) addOperation(op *ast.OperationDefinition) error {
	if err := g.validateOperation(op); err != nil {
		return err
	}

	queryDoc := &ast.QueryDocument{
		Operations: ast.OperationList{op},
		Fragments:  g.usedFragments(op),
	}
	g.preprocessQueryDocument(queryDoc)

	var builder strings.Builder
	f := formatter.NewFormatter(&builder)
	f.FormatQueryDocument(queryDoc)

	commentLines, directive, err := g.parsePrecedingComment(op, nil, op.Position, nil)
	if err != nil {
		return err
	}

	inputType, err := g.convertArguments(op, directive)
	if err != nil {
		return err
	}

	responseType, err := g.convertOperation(op, directive)
	if err != nil {
		return err
	}

	var docComment string
	if commentLines != "" {
		docComment = "// " + strings.ReplaceAll(commentLines, "\n", "\n// ")
	}

	// If the filename is a pseudo-filename filename.go:startline, just
	// put the filename in the export; we don't figure out the line offset
	// anyway, and if you want to check those exports in they will change a
	// lot if they have line numbers.
	// TODO: refactor to use the errorPos machinery for this
	sourceFilename := op.Position.Src.Name
	if i := strings.LastIndex(sourceFilename, ":"); i != -1 {
		sourceFilename = sourceFilename[:i]
	}

	g.Operations = append(g.Operations, &operation{
		Type: op.Operation,
		Name: op.Name,
		Doc:  docComment,
		// The newline just makes it format a little nicer.  We add it here
		// rather than in the template so exported operations will match
		// *exactly* what we send to the server.
		Body:           "\n" + builder.String(),
		Input:          inputType,
		ResponseName:   responseType.Reference(),
		SourceFilename: sourceFilename,
		Config:         g.Config, // for the convenience of the template
	})

	return nil
}

// Generate is the main programmatic entrypoint to genqlient, and generates and
// returns Go source code based on the given configuration.
//
// See [Config] for more on creating a configuration.  The return value is a
// map from filename to the generated file-content (e.g. Go source).  Callers
// who don't want to manage reading and writing the files should call [Main].
func Generate(config *Config) (map[string][]byte, error) {
	// Step 1: Read in the schema and operations from the files defined by the
	// config (and validate the operations against the schema).  This is all
	// defined in parse.go.
	schema, err := getSchema(config.Schema)
	if err != nil {
		return nil, err
	}

	document, err := getAndValidateQueries(config.baseDir, config.Operations, schema)
	if err != nil {
		return nil, err
	}

	// TODO(benkraft): we could also allow this, and generate an empty file
	// with just the package-name, if it turns out to be more convenient that
	// way.  (As-is, we generate a broken file, with just (unused) imports.)
	if len(document.Operations) == 0 {
		// Hard to have a position when there are no operations :(
		return nil, errorf(nil,
			"no queries found, looked in: %v (configure this in genqlient.yaml)",
			strings.Join(config.Operations, ", "))
	}

	// Step 2: For each operation and fragment, convert it into data structures
	// representing Go types (defined in types.go).  The bulk of this logic is
	// in convert.go, and it additionally updates g.typeMap to include all the
	// types it needs.
	g := newGenerator(config, schema, document.Fragments)
	for _, op := range document.Operations {
		if err = g.addOperation(op); err != nil {
			return nil, err
		}
	}

	// Step 3: Glue it all together!
	//
	// First, write the types (from g.typeMap) and operations to a temporary
	// buffer, since they affect what imports we'll put in the header.
	var bodyBuf bytes.Buffer
	err = g.WriteTypes(&bodyBuf)
	if err != nil {
		return nil, err
	}

	// Sort operations to guarantee a stable order
	sort.Slice(g.Operations, func(i, j int) bool {
		return g.Operations[i].Name < g.Operations[j].Name
	})

	for _, operation := range g.Operations {
		err = g.render("operation.go.tmpl", &bodyBuf, operation)
		if err != nil {
			return nil, err
		}
	}

	// The header also needs to reference some context types, which it does
	// after it writes the imports, so we need to preregister those imports.
	if g.Config.ContextType != "-" {
		_, err = g.ref("context.Context")
		if err != nil {
			return nil, err
		}
		if g.Config.ContextType != "context.Context" {
			_, err = g.ref(g.Config.ContextType)
			if err != nil {
				return nil, err
			}
		}
	}

	// Now really glue it all together, and format.
	var buf bytes.Buffer
	err = g.render("header.go.tmpl", &buf, g)
	if err != nil {
		return nil, err
	}
	_, err = io.Copy(&buf, &bodyBuf)
	if err != nil {
		return nil, err
	}

	unformatted := buf.Bytes()
	formatted, err := format.Source(unformatted)
	if err != nil {
		return nil, goSourceError("gofmt", unformatted, err)
	}
	importsed, err := imports.Process(config.Generated, formatted, nil)
	if err != nil {
		return nil, goSourceError("goimports", formatted, err)
	}

	retval := map[string][]byte{
		config.Generated: importsed,
	}

	if config.ExportOperations != "" {
		// We use MarshalIndent so that the file is human-readable and
		// slightly more likely to be git-mergeable (if you check it in).  In
		// general it's never going to be used anywhere where space is an
		// issue -- it doesn't go in your binary or anything.
		retval[config.ExportOperations], err = json.MarshalIndent(
			exportedOperations{Operations: g.Operations}, "", "  ")
		if err != nil {
			return nil, errorf(nil, "unable to export queries: %v", err)
		}
	}

	return retval, nil
}
