from . import ast
from ..error import GraphQLSyntaxError
from .lexer import Lexer, TokenKind, get_token_desc, get_token_kind_desc
from .source import Source

__all__ = ['parse']


def parse(source, **kwargs):
    """Given a GraphQL source, parses it into a Document."""
    options = {'no_location': False, 'no_source': False}
    options.update(kwargs)
    source_obj = source

    if isinstance(source, str):
        source_obj = Source(source)

    parser = Parser(source_obj, options)
    return parse_document(parser)


def parse_value(source, **kwargs):
    options = {'no_location': False, 'no_source': False}
    options.update(kwargs)
    source_obj = source

    if isinstance(source, str):
        source_obj = Source(source)

    parser = Parser(source_obj, options)
    return parse_value_literal(parser, False)


class Parser(object):
    __slots__ = 'lexer', 'source', 'options', 'prev_end', 'token'

    def __init__(self, source, options):
        self.lexer = Lexer(source)
        self.source = source
        self.options = options
        self.prev_end = 0
        self.token = self.lexer.next_token()


class Loc(object):
    __slots__ = 'start', 'end', 'source'

    def __init__(self, start, end, source=None):
        self.start = start
        self.end = end
        self.source = source

    def __repr__(self):
        source = ' source={}'.format(self.source) if self.source else ''
        return '<Loc start={} end={}{}>'.format(self.start, self.end, source)

    def __eq__(self, other):
        return (
            isinstance(other, Loc) and
            self.start == other.start and
            self.end == other.end and
            self.source == other.source
        )


def loc(parser, start):
    """Returns a location object, used to identify the place in
    the source that created a given parsed object."""
    if parser.options['no_location']:
        return None

    if parser.options['no_source']:
        return Loc(start, parser.prev_end)

    return Loc(start, parser.prev_end, parser.source)


def advance(parser):
    """Moves the internal parser object to the next lexed token."""
    prev_end = parser.token.end
    parser.prev_end = prev_end
    parser.token = parser.lexer.next_token(prev_end)


def peek(parser, kind):
    """Determines if the next token is of a given kind"""
    return parser.token.kind == kind


def skip(parser, kind):
    """If the next token is of the given kind, return true after advancing
    the parser. Otherwise, do not change the parser state
    and throw an error."""
    match = parser.token.kind == kind
    if match:
        advance(parser)

    return match


def expect(parser, kind):
    """If the next token is of the given kind, return that token after
    advancing the parser. Otherwise, do not change the parser state and
    return False."""
    token = parser.token
    if token.kind == kind:
        advance(parser)
        return token

    raise GraphQLSyntaxError(
        parser.source,
        token.start,
        u'Expected {}, found {}'.format(
            get_token_kind_desc(kind),
            get_token_desc(token)
        )
    )


def expect_keyword(parser, value):
    """If the next token is a keyword with the given value, return that
    token after advancing the parser. Otherwise, do not change the parser
    state and return False."""
    token = parser.token
    if token.kind == TokenKind.NAME and token.value == value:
        advance(parser)
        return token

    raise GraphQLSyntaxError(
        parser.source,
        token.start,
        u'Expected "{}", found {}'.format(value, get_token_desc(token))
    )


def unexpected(parser, at_token=None):
    """Helper function for creating an error when an unexpected lexed token
    is encountered."""
    token = at_token or parser.token
    return GraphQLSyntaxError(
        parser.source,
        token.start,
        u'Unexpected {}'.format(get_token_desc(token))
    )


def any(parser, open_kind, parse_fn, close_kind):
    """Returns a possibly empty list of parse nodes, determined by
    the parse_fn. This list begins with a lex token of openKind
    and ends with a lex token of closeKind. Advances the parser
    to the next lex token after the closing token."""
    expect(parser, open_kind)
    nodes = []
    while not skip(parser, close_kind):
        nodes.append(parse_fn(parser))

    return nodes


def many(parser, open_kind, parse_fn, close_kind):
    """Returns a non-empty list of parse nodes, determined by
    the parse_fn. This list begins with a lex token of openKind
    and ends with a lex token of closeKind. Advances the parser
    to the next lex token after the closing token."""
    expect(parser, open_kind)
    nodes = [parse_fn(parser)]
    while not skip(parser, close_kind):
        nodes.append(parse_fn(parser))

    return nodes


def parse_name(parser):
    """Converts a name lex token into a name parse node."""
    token = expect(parser, TokenKind.NAME)
    return ast.Name(
        value=token.value,
        loc=loc(parser, token.start)
    )


# Implements the parsing rules in the Document section.

def parse_document(parser):
    start = parser.token.start
    definitions = []
    while True:
        definitions.append(parse_definition(parser))

        if skip(parser, TokenKind.EOF):
            break

    return ast.Document(
        definitions=definitions,
        loc=loc(parser, start)
    )


def parse_definition(parser):
    if peek(parser, TokenKind.BRACE_L):
        return parse_operation_definition(parser)

    if peek(parser, TokenKind.NAME):
        name = parser.token.value

        if name in ('query', 'mutation', 'subscription'):
            return parse_operation_definition(parser)
        elif name == 'fragment':
            return parse_fragment_definition(parser)
        elif name in ('schema', 'scalar', 'type', 'interface', 'union', 'enum', 'input', 'extend', 'directive'):
            return parse_type_system_definition(parser)

    raise unexpected(parser)


# Implements the parsing rules in the Operations section.
def parse_operation_definition(parser):
    start = parser.token.start
    if peek(parser, TokenKind.BRACE_L):
        return ast.OperationDefinition(
            operation='query',
            name=None,
            variable_definitions=None,
            directives=[],
            selection_set=parse_selection_set(parser),
            loc=loc(parser, start)
        )

    operation = parse_operation_type(parser)

    name = None
    if peek(parser, TokenKind.NAME):
        name = parse_name(parser)

    return ast.OperationDefinition(
        operation=operation,
        name=name,
        variable_definitions=parse_variable_definitions(parser),
        directives=parse_directives(parser),
        selection_set=parse_selection_set(parser),
        loc=loc(parser, start)
    )


def parse_operation_type(parser):
    operation_token = expect(parser, TokenKind.NAME)
    operation = operation_token.value
    if operation == 'query':
        return 'query'
    elif operation == 'mutation':
        return 'mutation'
    elif operation == 'subscription':
        return 'subscription'

    raise unexpected(parser, operation_token)


def parse_variable_definitions(parser):
    if peek(parser, TokenKind.PAREN_L):
        return many(
            parser,
            TokenKind.PAREN_L,
            parse_variable_definition,
            TokenKind.PAREN_R
        )

    return []


def parse_variable_definition(parser):
    start = parser.token.start

    return ast.VariableDefinition(
        variable=parse_variable(parser),
        type=expect(parser, TokenKind.COLON) and parse_type(parser),
        default_value=parse_value_literal(parser, True) if skip(parser, TokenKind.EQUALS) else None,
        loc=loc(parser, start)
    )


def parse_variable(parser):
    start = parser.token.start
    expect(parser, TokenKind.DOLLAR)

    return ast.Variable(
        name=parse_name(parser),
        loc=loc(parser, start)
    )


def parse_selection_set(parser):
    start = parser.token.start
    return ast.SelectionSet(
        selections=many(parser, TokenKind.BRACE_L, parse_selection, TokenKind.BRACE_R),
        loc=loc(parser, start)
    )


def parse_selection(parser):
    if peek(parser, TokenKind.SPREAD):
        return parse_fragment(parser)
    else:
        return parse_field(parser)


def parse_field(parser):
    # Corresponds to both Field and Alias in the spec
    start = parser.token.start

    name_or_alias = parse_name(parser)
    if skip(parser, TokenKind.COLON):
        alias = name_or_alias
        name = parse_name(parser)
    else:
        alias = None
        name = name_or_alias

    return ast.Field(
        alias=alias,
        name=name,
        arguments=parse_arguments(parser),
        directives=parse_directives(parser),
        selection_set=parse_selection_set(parser) if peek(parser, TokenKind.BRACE_L) else None,
        loc=loc(parser, start)
    )


def parse_arguments(parser):
    if peek(parser, TokenKind.PAREN_L):
        return many(
            parser, TokenKind.PAREN_L,
            parse_argument, TokenKind.PAREN_R)

    return []


def parse_argument(parser):
    start = parser.token.start

    return ast.Argument(
        name=parse_name(parser),
        value=expect(parser, TokenKind.COLON) and parse_value_literal(parser, False),
        loc=loc(parser, start)
    )


# Implements the parsing rules in the Fragments section.

def parse_fragment(parser):
    # Corresponds to both FragmentSpread and InlineFragment in the spec
    start = parser.token.start
    expect(parser, TokenKind.SPREAD)

    if peek(parser, TokenKind.NAME) and parser.token.value != 'on':
        return ast.FragmentSpread(
            name=parse_fragment_name(parser),
            directives=parse_directives(parser),
            loc=loc(parser, start)
        )

    type_condition = None
    if parser.token.value == 'on':
        advance(parser)
        type_condition = parse_named_type(parser)

    return ast.InlineFragment(
        type_condition=type_condition,
        directives=parse_directives(parser),
        selection_set=parse_selection_set(parser),
        loc=loc(parser, start)
    )


def parse_fragment_definition(parser):
    start = parser.token.start
    expect_keyword(parser, 'fragment')

    return ast.FragmentDefinition(
        name=parse_fragment_name(parser),
        type_condition=expect_keyword(parser, 'on') and parse_named_type(parser),
        directives=parse_directives(parser),
        selection_set=parse_selection_set(parser),
        loc=loc(parser, start)
    )


def parse_fragment_name(parser):
    if parser.token.value == 'on':
        raise unexpected(parser)

    return parse_name(parser)


def parse_value_literal(parser, is_const):
    token = parser.token
    if token.kind == TokenKind.BRACKET_L:
        return parse_list(parser, is_const)

    elif token.kind == TokenKind.BRACE_L:
        return parse_object(parser, is_const)

    elif token.kind == TokenKind.INT:
        advance(parser)
        return ast.IntValue(value=token.value, loc=loc(parser, token.start))

    elif token.kind == TokenKind.FLOAT:
        advance(parser)
        return ast.FloatValue(value=token.value, loc=loc(parser, token.start))

    elif token.kind == TokenKind.STRING:
        advance(parser)
        return ast.StringValue(value=token.value, loc=loc(parser, token.start))

    elif token.kind == TokenKind.NAME:
        if token.value in ('true', 'false'):
            advance(parser)
            return ast.BooleanValue(value=token.value == 'true', loc=loc(parser, token.start))

        if token.value != 'null':
            advance(parser)
            return ast.EnumValue(value=token.value, loc=loc(parser, token.start))

    elif token.kind == TokenKind.DOLLAR:
        if not is_const:
            return parse_variable(parser)

    raise unexpected(parser)


# Implements the parsing rules in the Values section.
def parse_variable_value(parser):
    return parse_value_literal(parser, False)


def parse_const_value(parser):
    return parse_value_literal(parser, True)


def parse_list(parser, is_const):
    start = parser.token.start
    item = parse_const_value if is_const else parse_variable_value

    return ast.ListValue(
        values=any(
            parser, TokenKind.BRACKET_L,
            item, TokenKind.BRACKET_R),
        loc=loc(parser, start)
    )


def parse_object(parser, is_const):
    start = parser.token.start
    expect(parser, TokenKind.BRACE_L)
    fields = []

    while not skip(parser, TokenKind.BRACE_R):
        fields.append(parse_object_field(parser, is_const))

    return ast.ObjectValue(fields=fields, loc=loc(parser, start))


def parse_object_field(parser, is_const):
    start = parser.token.start
    return ast.ObjectField(
        name=parse_name(parser),
        value=expect(parser, TokenKind.COLON) and parse_value_literal(parser, is_const),
        loc=loc(parser, start)
    )


# Implements the parsing rules in the Directives section.

def parse_directives(parser):
    directives = []
    while peek(parser, TokenKind.AT):
        directives.append(parse_directive(parser))
    return directives


def parse_directive(parser):
    start = parser.token.start
    expect(parser, TokenKind.AT)

    return ast.Directive(
        name=parse_name(parser),
        arguments=parse_arguments(parser),
        loc=loc(parser, start),
    )


# Implements the parsing rules in the Types section.
def parse_type(parser):
    """Handles the 'Type': TypeName, ListType, and NonNullType
    parsing rules."""
    start = parser.token.start
    if skip(parser, TokenKind.BRACKET_L):
        ast_type = parse_type(parser)
        expect(parser, TokenKind.BRACKET_R)
        ast_type = ast.ListType(type=ast_type, loc=loc(parser, start))

    else:
        ast_type = parse_named_type(parser)

    if skip(parser, TokenKind.BANG):
        return ast.NonNullType(type=ast_type, loc=loc(parser, start))

    return ast_type


def parse_named_type(parser):
    start = parser.token.start
    return ast.NamedType(
        name=parse_name(parser),
        loc=loc(parser, start),
    )


def parse_type_system_definition(parser):
    '''
      TypeSystemDefinition :
        - SchemaDefinition
        - TypeDefinition
        - TypeExtensionDefinition
        - DirectiveDefinition

      TypeDefinition :
      - ScalarTypeDefinition
      - ObjectTypeDefinition
      - InterfaceTypeDefinition
      - UnionTypeDefinition
      - EnumTypeDefinition
      - InputObjectTypeDefinition
    '''
    if not peek(parser, TokenKind.NAME):
        raise unexpected(parser)

    name = parser.token.value

    if name == 'schema':
        return parse_schema_definition(parser)

    elif name == 'scalar':
        return parse_scalar_type_definition(parser)

    elif name == 'type':
        return parse_object_type_definition(parser)

    elif name == 'interface':
        return parse_interface_type_definition(parser)

    elif name == 'union':
        return parse_union_type_definition(parser)

    elif name == 'enum':
        return parse_enum_type_definition(parser)

    elif name == 'input':
        return parse_input_object_type_definition(parser)

    elif name == 'extend':
        return parse_type_extension_definition(parser)

    elif name == 'directive':
        return parse_directive_definition(parser)

    raise unexpected(parser)


def parse_schema_definition(parser):
    start = parser.token.start
    expect_keyword(parser, 'schema')
    directives = parse_directives(parser)
    operation_types = many(
        parser,
        TokenKind.BRACE_L,
        parse_operation_type_definition,
        TokenKind.BRACE_R
    )

    return ast.SchemaDefinition(
        directives=directives,
        operation_types=operation_types,
        loc=loc(parser, start)
    )


def parse_operation_type_definition(parser):
    start = parser.token.start
    operation = parse_operation_type(parser)
    expect(parser, TokenKind.COLON)

    return ast.OperationTypeDefinition(
        operation=operation,
        type=parse_named_type(parser),
        loc=loc(parser, start)
    )


def parse_scalar_type_definition(parser):
    start = parser.token.start
    expect_keyword(parser, 'scalar')

    return ast.ScalarTypeDefinition(
        name=parse_name(parser),
        directives=parse_directives(parser),
        loc=loc(parser, start),
    )


def parse_object_type_definition(parser):
    start = parser.token.start
    expect_keyword(parser, 'type')
    return ast.ObjectTypeDefinition(
        name=parse_name(parser),
        interfaces=parse_implements_interfaces(parser),
        directives=parse_directives(parser),
        fields=any(
            parser,
            TokenKind.BRACE_L,
            parse_field_definition,
            TokenKind.BRACE_R
        ),
        loc=loc(parser, start),
    )


def parse_implements_interfaces(parser):
    types = []
    if parser.token.value == 'implements':
        advance(parser)

        while True:
            types.append(parse_named_type(parser))

            if not peek(parser, TokenKind.NAME):
                break

    return types


def parse_field_definition(parser):
    start = parser.token.start

    return ast.FieldDefinition(
        name=parse_name(parser),
        arguments=parse_argument_defs(parser),
        type=expect(parser, TokenKind.COLON) and parse_type(parser),
        directives=parse_directives(parser),
        loc=loc(parser, start),
    )


def parse_argument_defs(parser):
    if not peek(parser, TokenKind.PAREN_L):
        return []

    return many(parser, TokenKind.PAREN_L, parse_input_value_def, TokenKind.PAREN_R)


def parse_input_value_def(parser):
    start = parser.token.start

    return ast.InputValueDefinition(
        name=parse_name(parser),
        type=expect(parser, TokenKind.COLON) and parse_type(parser),
        default_value=parse_const_value(parser) if skip(parser, TokenKind.EQUALS) else None,
        directives=parse_directives(parser),
        loc=loc(parser, start),
    )


def parse_interface_type_definition(parser):
    start = parser.token.start
    expect_keyword(parser, 'interface')

    return ast.InterfaceTypeDefinition(
        name=parse_name(parser),
        directives=parse_directives(parser),
        fields=any(parser, TokenKind.BRACE_L, parse_field_definition, TokenKind.BRACE_R),
        loc=loc(parser, start),
    )


def parse_union_type_definition(parser):
    start = parser.token.start
    expect_keyword(parser, 'union')

    return ast.UnionTypeDefinition(
        name=parse_name(parser),
        directives=parse_directives(parser),
        types=expect(parser, TokenKind.EQUALS) and parse_union_members(parser),
        loc=loc(parser, start),
    )


def parse_union_members(parser):
    members = []

    while True:
        members.append(parse_named_type(parser))

        if not skip(parser, TokenKind.PIPE):
            break

    return members


def parse_enum_type_definition(parser):
    start = parser.token.start
    expect_keyword(parser, 'enum')

    return ast.EnumTypeDefinition(
        name=parse_name(parser),
        directives=parse_directives(parser),
        values=many(parser, TokenKind.BRACE_L, parse_enum_value_definition, TokenKind.BRACE_R),
        loc=loc(parser, start),
    )


def parse_enum_value_definition(parser):
    start = parser.token.start

    return ast.EnumValueDefinition(
        name=parse_name(parser),
        directives=parse_directives(parser),
        loc=loc(parser, start),
    )


def parse_input_object_type_definition(parser):
    start = parser.token.start
    expect_keyword(parser, 'input')

    return ast.InputObjectTypeDefinition(
        name=parse_name(parser),
        directives=parse_directives(parser),
        fields=any(parser, TokenKind.BRACE_L, parse_input_value_def, TokenKind.BRACE_R),
        loc=loc(parser, start),
    )


def parse_type_extension_definition(parser):
    start = parser.token.start
    expect_keyword(parser, 'extend')

    return ast.TypeExtensionDefinition(
        definition=parse_object_type_definition(parser),
        loc=loc(parser, start)
    )


def parse_directive_definition(parser):
    start = parser.token.start
    expect_keyword(parser, 'directive')
    expect(parser, TokenKind.AT)

    name = parse_name(parser)
    args = parse_argument_defs(parser)
    expect_keyword(parser, 'on')

    locations = parse_directive_locations(parser)
    return ast.DirectiveDefinition(
        name=name,
        locations=locations,
        arguments=args,
        loc=loc(parser, start)
    )


def parse_directive_locations(parser):
    locations = []

    while True:
        locations.append(parse_name(parser))

        if not skip(parser, TokenKind.PIPE):
            break

    return locations
