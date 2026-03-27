package attribute

import "reflect"

func asSlice[T any](v any) []T {
	rv := reflect.ValueOf(v)
	if rv.Kind() != reflect.Array {
		return nil
	}
	cpy := make([]T, rv.Len())
	if len(cpy) > 0 {
		_ = reflect.Copy(reflect.ValueOf(cpy), rv)
	}
	return cpy
}
