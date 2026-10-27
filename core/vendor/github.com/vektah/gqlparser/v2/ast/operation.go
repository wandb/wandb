package ast

type Operation string

const (
	Query        Operation = "query"
	Mutation     Operation = "mutation"
	Subscription Operation = "subscription"
)

type OperationDefinition struct {
	Description         string
	Operation           Operation
	Name                string
	VariableDefinitions VariableDefinitionList
	Directives          DirectiveList
	SelectionSet        SelectionSet
	Position            *Position `dump:"-" json:"-"`
	Comment             *CommentGroup
}

type VariableDefinition struct {
	Description  string
	Variable     string
	Type         *Type
	DefaultValue *Value
	Directives   DirectiveList
	Position     *Position `dump:"-" json:"-"`
	Comment      *CommentGroup

	// Requires validation
	Definition *Definition
	Used       bool `dump:"-"`
}
