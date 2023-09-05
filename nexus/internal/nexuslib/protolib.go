package nexuslib

import (
	"strings"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
)

func isBoolMessage(m protoreflect.Message) bool {
	fds := m.Descriptor().Fields()
	for i := 0; i < fds.Len(); i++ {
		if fds.Get(i).Kind() != protoreflect.BoolKind {
			return false
		}
	}
	return true
}

func ProtoEncodeToDict(p proto.Message) map[int]interface{} {
	pm := p.ProtoReflect()

	m := make(map[int]interface{})
	pm.Range(func(fd protoreflect.FieldDescriptor, v protoreflect.Value) bool {
		num := fd.Number()
		name := fd.Name()
		if strings.HasPrefix(string(name), "_") {
			return true
		}
		switch fd.Kind() {
		case protoreflect.Int32Kind:
			m[int(num)] = v.Int()
		case protoreflect.StringKind:
			m[int(num)] = v.String()
		case protoreflect.EnumKind:
			m[int(num)] = v.Enum()
		case protoreflect.MessageKind:
			pm2 := pm.Get(fd).Message()
			// TODO(perf2): cache isBoolMessage based on field number
			bmsg := isBoolMessage(pm2)
			if bmsg {
				var lst []int
				pm2.Range(func(fd2 protoreflect.FieldDescriptor, v2 protoreflect.Value) bool {
					lst = append(lst, int(fd2.Number()))
					return true
				})
				m[int(num)] = lst
			} else {
				m2 := make(map[int]interface{})
				pm2.Range(func(fd2 protoreflect.FieldDescriptor, v2 protoreflect.Value) bool {
					// NOTE: only messages of strings are currently used
					if fd2.Kind() == protoreflect.StringKind {
						m2[int(fd2.Number())] = v2.String()
					}
					return true
				})
				m[int(num)] = m2
			}

		}
		return true
	})

	return m
}
