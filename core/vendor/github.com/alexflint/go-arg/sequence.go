package arg

import (
	"fmt"
	"reflect"
	"strings"

	scalar "github.com/alexflint/go-scalar"
)

// setSliceOrMap parses a sequence of strings into a slice or map. If clear is
// true then any values already in the slice or map are first removed.
func setSliceOrMap(dest reflect.Value, values []string, clear bool) error {
	if !dest.CanSet() {
		return fmt.Errorf("field is not writable")
	}

	t := dest.Type()
	if t.Kind() == reflect.Ptr {
		dest = dest.Elem()
		t = t.Elem()
	}

	switch t.Kind() {
	case reflect.Slice:
		return setSlice(dest, values, clear)
	case reflect.Map:
		return setMap(dest, values, clear)
	default:
		return fmt.Errorf("setSliceOrMap cannot insert values into a %v", t)
	}
}

// setSlice parses a sequence of strings and inserts them into a slice. If clear
// is true then any values already in the slice are removed.
func setSlice(dest reflect.Value, values []string, clear bool) error {
	var ptr bool
	elem := dest.Type().Elem()
	if elem.Kind() == reflect.Ptr && !elem.Implements(textUnmarshalerType) {
		ptr = true
		elem = elem.Elem()
	}

	// clear the slice in case default values exist
	if clear && !dest.IsNil() {
		dest.SetLen(0)
	}

	// parse the values one-by-one
	for _, s := range values {
		v := reflect.New(elem)
		if err := scalar.ParseValue(v.Elem(), s); err != nil {
			return err
		}
		if !ptr {
			v = v.Elem()
		}
		dest.Set(reflect.Append(dest, v))
	}
	return nil
}

// setMap parses a sequence of name=value strings and inserts them into a map.
// If clear is true then any values already in the map are removed.
func setMap(dest reflect.Value, values []string, clear bool) error {
	// determine the key and value type
	var keyIsPtr bool
	keyType := dest.Type().Key()
	if keyType.Kind() == reflect.Ptr && !keyType.Implements(textUnmarshalerType) {
		keyIsPtr = true
		keyType = keyType.Elem()
	}

	var valIsPtr bool
	valType := dest.Type().Elem()
	if valType.Kind() == reflect.Ptr && !valType.Implements(textUnmarshalerType) {
		valIsPtr = true
		valType = valType.Elem()
	}

	// clear the slice in case default values exist
	if clear && !dest.IsNil() {
		for _, k := range dest.MapKeys() {
			dest.SetMapIndex(k, reflect.Value{})
		}
	}

	// allocate the map if it is not allocated
	if dest.IsNil() {
		dest.Set(reflect.MakeMap(dest.Type()))
	}

	// parse the values one-by-one
	for _, s := range values {
		// split at the first equals sign
		pos := strings.Index(s, "=")
		if pos == -1 {
			return fmt.Errorf("cannot parse %q into a map, expected format key=value", s)
		}

		// parse the key
		k := reflect.New(keyType)
		if err := scalar.ParseValue(k.Elem(), s[:pos]); err != nil {
			return err
		}
		if !keyIsPtr {
			k = k.Elem()
		}

		// parse the value
		v := reflect.New(valType)
		if err := scalar.ParseValue(v.Elem(), s[pos+1:]); err != nil {
			return err
		}
		if !valIsPtr {
			v = v.Elem()
		}

		// add it to the map
		dest.SetMapIndex(k, v)
	}
	return nil
}
