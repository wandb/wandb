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

func (*ListType) isParams_ParamsType() {}

type UnionType struct {
	AllowedTypes []TypeRepresentation `json:"allowed_types"`
}

func (*UnionType) isParams_ParamsType() {}

type MapType struct {
	Type map[string]TypeRepresentation `json:"type_map"`
}

func (*MapType) isParams_ParamsType() {}

type TypeRepresentation struct {
	Name   TypeName            `json:"wb_type"`
	Params isParams_ParamsType `json:"params,omitempty"`
}

type isParams_ParamsType interface {
	isParams_ParamsType()
}

func ResolveTypes(data interface{}) TypeRepresentation {
	return resolveTypes(data)
}

func resolveTypes(data interface{}) TypeRepresentation {
	// TODO: need to properly understand how to handle invalid types

	switch v := data.(type) {
	case map[string]interface{}:
		result := make(map[string]TypeRepresentation)
		for key, value := range v {
			if key != "_wandb" {
				result[key] = resolveTypes(value)
			}
		}
		return TypeRepresentation{
			Name: MapTypeName,
			Params: &MapType{
				Type: result,
			},
		}

	case []interface{}:
		result := make(map[TypeName]TypeRepresentation)
		for _, elem := range v {
			resolved := resolveTypes(elem)
			// TODO: this is not correct if we have a complex type that is a bit different
			// for example: [[1, 2, 3], [1, 2, "3"]] should be union but it will be list
			result[resolved.Name] = resolved
		}
		if len(result) == 0 {
			return TypeRepresentation{
				Name: ListTypeName,
				Params: &ListType{
					ElementType: TypeRepresentation{
						Name: UnknownTypeName,
					},
					Length: len(v),
				},
			}
		}
		if len(result) == 1 {
			for _, elem := range result {
				return TypeRepresentation{
					Name: ListTypeName,
					Params: &ListType{
						ElementType: elem,
						Length:      len(v),
					},
				}
			}
		}

		allowed := make([]TypeRepresentation, 0, len(result))
		for _, elem := range result {
			allowed = append(allowed, elem)
		}
		return TypeRepresentation{
			Name: ListTypeName,
			Params: &ListType{
				ElementType: TypeRepresentation{
					Name: UnionTypeName,
					Params: &UnionType{
						AllowedTypes: allowed,
					},
				},
				Length: len(v),
			},
		}
	case int, int8, int16, int32, int64:
		return TypeRepresentation{
			Name: NumberTypeName,
		}
	case uint, uint8, uint16, uint32, uint64:
		return TypeRepresentation{
			Name: NumberTypeName,
		}
	case float32, float64:
		return TypeRepresentation{
			Name: NumberTypeName,
		}
	case string:
		return TypeRepresentation{
			Name: StringTypeName,
		}

	case bool:
		return TypeRepresentation{
			Name: BooleanTypeName,
		}

	case nil:
		return TypeRepresentation{
			Name: NoneTypeName,
		}
	}

	return TypeRepresentation{
		Name: UnknownTypeName,
	}
}
