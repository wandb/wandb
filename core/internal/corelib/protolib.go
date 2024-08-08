package corelib

import (
	"strconv"
	"strings"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
)

// isBoolMessage reports whether all fields in the message are boolean.
func isBoolMessage(m protoreflect.Message) bool {
	fds := m.Descriptor().Fields()
	for i := 0; i < fds.Len(); i++ {
		if fds.Get(i).Kind() != protoreflect.BoolKind {
			return false
		}
	}
	return true
}

// ProtoEncodeToDict represents a proto as a map with field numbers as keys.
//
// This function is very specific to W&B telemetry proto and is not a general
// proto conversion function.
//
//   - Fields prefixed with an underscore or having an unsupported type are
//     skipped
//   - Nested messages are only supported if they consist entirely of bools
//     or strings
//
// All keys in the result and its nested maps are strings, and all values are
// string/int64/float64/slices and maps of those so that the result can be
// converted to JSON using wandb/simplejsonext.
func ProtoEncodeToDict(p proto.Message) map[string]any {
	pm := p.ProtoReflect()

	m := make(map[string]any)
	pm.Range(func(fd protoreflect.FieldDescriptor, v protoreflect.Value) bool {
		num := fd.Number()
		name := fd.Name()

		if strings.HasPrefix(string(name), "_") {
			return true
		}

		switch fd.Kind() {
		case protoreflect.Int32Kind:
			m[strconv.Itoa(int(num))] = v.Int()

		case protoreflect.StringKind:
			m[strconv.Itoa(int(num))] = v.String()

		case protoreflect.EnumKind:
			m[strconv.Itoa(int(num))] = int64(v.Enum())

		case protoreflect.MessageKind:
			pm2 := pm.Get(fd).Message()
			// TODO(perf2): cache isBoolMessage based on field number
			bmsg := isBoolMessage(pm2)
			if bmsg {
				var lst []int64
				pm2.Range(func(fd2 protoreflect.FieldDescriptor, v2 protoreflect.Value) bool {
					lst = append(lst, int64(fd2.Number()))
					return true
				})
				m[strconv.Itoa(int(num))] = lst
			} else {
				m2 := make(map[string]any)
				pm2.Range(func(fd2 protoreflect.FieldDescriptor, v2 protoreflect.Value) bool {
					// NOTE: only messages of strings are currently used
					if fd2.Kind() == protoreflect.StringKind {
						m2[strconv.Itoa(int(fd2.Number()))] = v2.String()
					}
					return true
				})
				m[strconv.Itoa(int(num))] = m2
			}
		}

		return true
	})

	return m
}
