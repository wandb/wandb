package data_types

type TypeName string

const (
	StringTypeName  TypeName = "string"
	BooleanTypeName TypeName = "boolean"
	NoneTypeName    TypeName = "none"
	ListTypeName    TypeName = "list"
	UnionTypeName   TypeName = "union"
	MapTypeName     TypeName = "typedDict"
	InvalidTypeName TypeName = "invalid"
	UnknownTypeName TypeName = "unknown"
	NumberTypeName  TypeName = "number"
)

type ListType struct {
	ElementType TypeRepresentation `json:"element_type"`
	Length      int                `json:"length"`
}

func (*ListType) isParam_ParamType() {}

type UnionType struct {
	AllowedTypes []TypeRepresentation `json:"allowed_types"`
}

func (*UnionType) isParam_ParamType() {}

type MapType struct {
	Type map[string]TypeRepresentation `json:"type_map"`
}

func (*MapType) isParam_ParamType() {}

type TypeRepresentation struct {
	Type   TypeName          `json:"wb_type"`
	Params isParam_ParamType `json:"params,omitempty"`
}

type isParam_ParamType interface {
	isParam_ParamType()
}

func GenerateTypeRepresentation(data interface{}) TypeRepresentation {
	return resolveTypes(data)
}

func resolveTypes(data any, invalid ...bool) TypeRepresentation {
	encounteredInvalid := len(invalid) > 0 && invalid[0]

	switch v := data.(type) {
	case map[string]any:
		result := TypeRepresentation{
			Type: MapTypeName,
			Params: &MapType{
				Type: map[string]TypeRepresentation{},
			},
		}
		for key, value := range v {
			if len(key) == 0 || key[0] != '_' {
				result.Params.(*MapType).Type[key] = resolveTypes(value)
			}
		}
		return result

	case []any:
		if len(v) == 0 {
			return TypeRepresentation{
				Type: "list",
				Params: &ListType{
					ElementType: TypeRepresentation{Type: UnknownTypeName},
					Length:      0,
				},
			}
		}
		elemType := resolveTypes(v[0])
		isInvalid := elemType.Type == InvalidTypeName
		for _, elem := range v[1:] {
			elemRep := resolveTypes(elem, isInvalid)
			if elemRep.Type != elemType.Type {
				elemType = TypeRepresentation{
					Type: UnionTypeName,
					Params: &UnionType{
						AllowedTypes: []TypeRepresentation{elemType, elemRep},
					},
				}
				break
			}
		}
		if encounteredInvalid {
			elemType.Type = InvalidTypeName
		}
		return TypeRepresentation{
			Type: "list",
			Params: &ListType{
				ElementType: elemType,
				Length:      len(v),
			},
		}

	case int, float64:
		return TypeRepresentation{
			Type: NumberTypeName,
		}

	case string:
		return TypeRepresentation{
			Type: StringTypeName,
		}

	case bool:
		return TypeRepresentation{
			Type: BooleanTypeName,
		}

	case nil:
		return TypeRepresentation{
			Type: NoneTypeName,
		}
	}

	if encounteredInvalid {
		return TypeRepresentation{
			Type: UnknownTypeName,
		}
	}
	return TypeRepresentation{
		Type: InvalidTypeName,
	}
}
