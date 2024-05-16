package simplejsonext

import (
	"math"
)

// WalkDeNaN recursively traverses a simple JSON value, recursively replacing
// NaN and Infinity values with a corresponding string value. This modifies
// objects and arrays in-place.
func WalkDeNaN(obj interface{}) interface{} {
	switch tobj := obj.(type) {
	case map[string]interface{}:
		for k, v := range tobj {
			tobj[k] = WalkDeNaN(v)
		}
		return tobj
	case []interface{}:
		for i, v := range tobj {
			tobj[i] = WalkDeNaN(v)
		}
		return tobj
	case float64:
		if math.IsNaN(tobj) {
			return "NaN"
		} else if math.IsInf(tobj, +1) {
			return "Infinity"
		} else if math.IsInf(tobj, -1) {
			return "-Infinity"
		} else {
			return tobj
		}
	default:
		return tobj
	}
}
