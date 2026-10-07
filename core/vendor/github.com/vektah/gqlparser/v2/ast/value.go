package ast

import (
	"fmt"
	"strconv"
	"strings"
)

type ValueKind int

const (
	Variable ValueKind = iota
	IntValue
	FloatValue
	StringValue
	BlockValue
	BooleanValue
	NullValue
	EnumValue
	ListValue
	ObjectValue
)

type Value struct {
	Raw      string
	Children ChildValueList
	Kind     ValueKind
	Position *Position `dump:"-" json:"-"`
	Comment  *CommentGroup

	// Require validation
	Definition             *Definition
	VariableDefinition     *VariableDefinition
	ExpectedType           *Type
	ExpectedTypeHasDefault bool
}

type ChildValue struct {
	Name     string
	Value    *Value
	Position *Position `dump:"-" json:"-"`
	Comment  *CommentGroup
}

// isUnsetVariable reports whether v is a variable reference with no supplied
// value and no default — it should be treated as absent, not null.
func (v *Value) isUnsetVariable(vars map[string]any) bool {
	if v.Kind != Variable {
		return false
	}
	if _, ok := vars[v.Raw]; ok {
		return false
	}
	return v.VariableDefinition == nil || v.VariableDefinition.DefaultValue == nil
}

func (v *Value) Value(vars map[string]any) (any, error) {
	if v == nil {
		return nil, nil
	}
	switch v.Kind {
	case Variable:
		if value, ok := vars[v.Raw]; ok {
			return value, nil
		}
		if v.VariableDefinition != nil && v.VariableDefinition.DefaultValue != nil {
			return v.VariableDefinition.DefaultValue.Value(vars)
		}
		return nil, nil
	case IntValue:
		return strconv.ParseInt(v.Raw, 10, 64)
	case FloatValue:
		return strconv.ParseFloat(v.Raw, 64)
	case StringValue, BlockValue, EnumValue:
		return v.Raw, nil
	case BooleanValue:
		return strconv.ParseBool(v.Raw)
	case NullValue:
		return nil, nil
	case ListValue:
		var val []any
		for _, elem := range v.Children {
			elemVal, err := elem.Value.Value(vars)
			if err != nil {
				return val, err
			}
			val = append(val, elemVal)
		}
		return val, nil
	case ObjectValue:
		val := map[string]any{}
		for _, elem := range v.Children {
			if elem.Value.isUnsetVariable(vars) {
				continue
			}
			elemVal, err := elem.Value.Value(vars)
			if err != nil {
				return val, err
			}
			val[elem.Name] = elemVal
		}
		return val, nil
	default:
		panic(fmt.Errorf("unknown value kind %d", v.Kind))
	}
}

func (v *Value) String() string {
	if v == nil {
		return "<nil>"
	}
	switch v.Kind {
	case Variable:
		return "$" + v.Raw
	case IntValue, FloatValue, EnumValue, BooleanValue, NullValue:
		return v.Raw
	case StringValue, BlockValue:
		return quoteString(v.Raw)
	case ListValue:
		var val []string
		for _, elem := range v.Children {
			val = append(val, elem.Value.String())
		}
		return "[" + strings.Join(val, ",") + "]"
	case ObjectValue:
		var val []string
		for _, elem := range v.Children {
			val = append(val, elem.Name+":"+elem.Value.String())
		}
		return "{" + strings.Join(val, ",") + "}"
	default:
		panic(fmt.Errorf("unknown value kind %d", v.Kind))
	}
}

func (v *Value) Dump() string {
	return v.String()
}

const hexDigitsUpper = "0123456789ABCDEF"

// mayNeedEscape reports whether b can begin an escape sequence. ASCII controls, '"', '\' and
// DEL always escape; 0xC2 only sometimes, since it leads both U+0080-U+009F, which graphql-js
// escapes, and U+00A0-U+00BF, which it leaves alone.
func mayNeedEscape(b byte) bool {
	return b < 0x20 || b == '"' || b == '\\' || b == 0x7f || b == 0xC2
}

// writeUnicodeEscape writes c as \u00XX, the upper-case hex form graphql-js emits.
func writeUnicodeEscape(b *strings.Builder, c byte) {
	b.WriteString(`\u00`)
	b.WriteByte(hexDigitsUpper[c>>4])
	b.WriteByte(hexDigitsUpper[c&0xf])
}

// quoteString quotes s as a GraphQL string literal, escaping the way graphql-js printString
// does. strconv.Quote is not a substitute: it emits Go-only escapes such as \x1b and \a that
// the GraphQL grammar rejects, and escapes printable non-ASCII that GraphQL accepts verbatim.
//
// It walks bytes rather than runes so that input which is not valid UTF-8 survives unaltered.
// Ranging over runes yields U+FFFD once per malformed byte, which would quietly rewrite a
// value the caller supplied, and would do so only for the strings that take the slow path.
func quoteString(s string) string {
	// Find where escaping has to start. Strings needing none take a single allocation and
	// never touch the Builder, which is the common case by a wide margin.
	i := 0
	for ; i < len(s); i++ {
		if mayNeedEscape(s[i]) {
			break
		}
	}
	if i == len(s) {
		return `"` + s + `"`
	}

	// Room for the quotes and a few escapes. Strings that escape more than that are rare
	// enough to leave to the Builder's own growth.
	var b strings.Builder
	b.Grow(len(s) + len(s)/8 + 2)
	b.WriteByte('"')
	b.WriteString(s[:i])
	for ; i < len(s); i++ {
		switch c := s[i]; c {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case 0xC2:
			// U+0080-U+009F encode as 0xC2 followed by the code point's own low byte, so
			// that second byte is the one to escape. 0xC2 also leads U+00A0-U+00BF, which
			// graphql-js prints as-is; those copy one byte at a time like anything else.
			if next := i + 1; next < len(s) && s[next] >= 0x80 && s[next] <= 0x9f {
				writeUnicodeEscape(&b, s[next])
				i = next // the loop's own i++ then steps past the pair
				continue
			}
			b.WriteByte(c)
		default:
			if c < 0x20 || c == 0x7f {
				writeUnicodeEscape(&b, c)
			} else {
				b.WriteByte(c)
			}
		}
	}
	b.WriteByte('"')
	return b.String()
}
