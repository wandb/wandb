package ast

func arg2map(
	defs ArgumentDefinitionList,
	args ArgumentList,
	vars map[string]any,
) map[string]any {
	result := map[string]any{}
	var err error

	for _, argDef := range defs {
		var val any
		var hasValue bool

		if argValue := args.ForName(argDef.Name); argValue != nil {
			if argValue.Value.Kind == Variable {
				val, hasValue = vars[argValue.Value.Raw]
			} else {
				val, err = argValue.Value.Value(vars)
				if err != nil {
					panic(err)
				}
				hasValue = true
			}
		}

		if !hasValue && argDef.DefaultValue != nil {
			val, err = argDef.DefaultValue.Value(vars)
			if err != nil {
				panic(err)
			}
			hasValue = true
		}

		if hasValue {
			result[argDef.Name] = val
		}
	}

	return result
}
