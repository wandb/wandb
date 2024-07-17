package simplejsonext

import (
	"encoding/base64"
	"fmt"
	"io"
	"math"
	"reflect"
	"strconv"
	"time"
)

var (
	nullBytes  = [...]byte{'n', 'u', 'l', 'l'}
	trueBytes  = [...]byte{'t', 'r', 'u', 'e'}
	falseBytes = [...]byte{'f', 'a', 'l', 's', 'e'}

	arrayOpen  = [...]byte{'['}
	arrayClose = [...]byte{']'}

	mapOpen  = [...]byte{'{'}
	mapClose = [...]byte{'}'}

	comma  = [...]byte{','}
	column = [...]byte{':'}

	hexChars = [...]byte{'0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'c', 'd', 'e', 'f'}
)

// Reusable object that can encode simple JSON values to any Writer.
type Emitter interface {
	// Writes the given value to the wrapped Writer. If the value or part of the
	// value is not a supported type, an error will be returned with JSON only
	// partially written.
	//
	// Supported types include: nil, bool, integers, floats, string, []byte
	// (as a base64 encoded string), time.Time (written as an RFC3339 string),
	// error (written as a string), and pointers/slices/string-keyed maps of
	// supported types.
	Emit(val any) error
	// Replaces the Writer that this Emitter writes to.
	Reset(io.Writer)
}

type emitter struct {
	w io.Writer
	s []byte
	a [128]byte
}

// Creates a new Emitter wrapping the given Writer.
func NewEmitter(w io.Writer) Emitter {
	e := &emitter{w: w}
	e.s = e.a[:0]
	return e
}

func (e *emitter) Reset(w io.Writer) {
	e.w = w
	if cap(e.s) > oversizedBuffer {
		e.s = e.a[:0]
	}
}

func (e *emitter) emitNil() (err error) {
	_, err = e.w.Write(nullBytes[:])
	return
}

func (e *emitter) emitBool(v bool) (err error) {
	if v {
		_, err = e.w.Write(trueBytes[:])
	} else {
		_, err = e.w.Write(falseBytes[:])
	}
	return
}

func (e *emitter) emitInt(v int64, _ int) (err error) {
	_, err = e.w.Write(strconv.AppendInt(e.s[:0], v, 10))
	return
}

func (e *emitter) emitUint(v uint64, _ int) (err error) {
	_, err = e.w.Write(strconv.AppendUint(e.s[:0], v, 10))
	return
}

func (e *emitter) emitFloat(v float64, bitSize int) (err error) {
	// AppendFloat writes NaN the way we want, but spells infinity values as
	// `+Inf` and `-Inf`, which we don't like as much.
	if math.IsInf(v, +1) {
		_, err = e.w.Write([]byte("Infinity"))
	} else if math.IsInf(v, -1) {
		_, err = e.w.Write([]byte("-Infinity"))
	} else {
		_, err = e.w.Write(strconv.AppendFloat(e.s[:0], v, 'g', -1, bitSize))
	}
	return
}

func (e *emitter) emitString(v string) (err error) {
	i := 0
	j := 0
	n := len(v)
	s := append(e.s[:0], '"')

	for j != n {
		b := v[j]
		j++

		switch b {
		case '"', '\\':
			// b = b

		case '\b':
			b = 'b'

		case '\f':
			b = 'f'

		case '\n':
			b = 'n'

		case '\r':
			b = 'r'

		case '\t':
			b = 't'

		default:
			if b < 32 {
				// Control characters not cased up above MUST be escaped.
				s = append(s, v[i:j-1]...)
				s = append(s, '\\', 'u', '0', '0', hexChars[(b&0xf0)>>4], hexChars[b&0xf])
				i = j
			}
			continue
		}

		s = append(s, v[i:j-1]...)
		s = append(s, '\\', b)
		i = j
	}

	s = append(s, v[i:j]...)
	s = append(s, '"')
	e.s = s[:0] // in case the buffer was reallocated

	_, err = e.w.Write(s)
	return
}

func (e *emitter) emitBytes(v []byte) (err error) {
	s := e.s[:0]
	n := base64.StdEncoding.EncodedLen(len(v)) + 2

	if cap(s) < n {
		s = make([]byte, 0, align(n, 1024))
		e.s = s
	}

	s = s[:n]
	s[0] = '"'
	base64.StdEncoding.Encode(s[1:], v)
	s[n-1] = '"'

	_, err = e.w.Write(s)
	return
}

func (e *emitter) emitTime(v time.Time) (err error) {
	s := e.s[:0]

	s = append(s, '"')
	s = v.AppendFormat(s, time.RFC3339Nano)
	s = append(s, '"')

	e.s = s[:0]
	_, err = e.w.Write(s)
	return
}

func (e *emitter) emitError(v error) (err error) {
	return e.emitString(v.Error())
}

func (e *emitter) emitArrayBegin(_ int) (err error) {
	_, err = e.w.Write(arrayOpen[:])
	return
}

func (e *emitter) emitArrayEnd() (err error) {
	_, err = e.w.Write(arrayClose[:])
	return
}

func (e *emitter) emitArrayNext() (err error) {
	_, err = e.w.Write(comma[:])
	return
}

func (e *emitter) emitMapBegin(_ int) (err error) {
	_, err = e.w.Write(mapOpen[:])
	return
}

func (e *emitter) emitMapEnd() (err error) {
	_, err = e.w.Write(mapClose[:])
	return
}

func (e *emitter) emitMapValue() (err error) {
	_, err = e.w.Write(column[:])
	return
}

func (e *emitter) emitMapNext() (err error) {
	_, err = e.w.Write(comma[:])
	return
}

func (e *emitter) Emit(v interface{}) (err error) {
	switch vt := v.(type) {
	case nil:
		return e.emitNil()
	case bool:
		return e.emitBool(vt)
	case int64:
		return e.emitInt(vt, 10)
	case int32:
		return e.emitInt(int64(vt), 10)
	case int:
		return e.emitInt(int64(vt), 10)
	case uint64:
		return e.emitUint(vt, 10)
	case uint32:
		return e.emitUint(uint64(vt), 10)
	case uint:
		return e.emitUint(uint64(vt), 10)
	case float64:
		return e.emitFloat(vt, 64)
	case float32:
		return e.emitFloat(float64(vt), 32)
	case string:
		return e.emitString(vt)
	case []any:
		err = e.emitArrayBegin(0)
		if err != nil {
			return
		}
		notFirst := false
		for _, av := range vt {
			if notFirst {
				err = e.emitArrayNext()
				if err != nil {
					return
				}
			}
			notFirst = true
			err = e.Emit(av)
			if err != nil {
				return
			}
		}
		return e.emitArrayEnd()
	case map[string]any:
		err = e.emitMapBegin(0)
		if err != nil {
			return
		}
		notFirst := false
		for key, value := range vt {
			if notFirst {
				err = e.emitMapNext()
				if err != nil {
					return
				}
			}
			notFirst = true
			err = e.emitString(key)
			if err != nil {
				return
			}
			err = e.emitMapValue()
			if err != nil {
				return
			}
			err = e.Emit(value)
			if err != nil {
				return
			}
		}
		return e.emitMapEnd()
	case []byte:
		return e.emitBytes(vt)
	case time.Time:
		return e.emitTime(vt)
	case error:
		return e.emitError(vt)
	default:
		ty := reflect.TypeOf(vt)
		if ty.Kind() == reflect.Pointer {
			rp := reflect.ValueOf(v) // rp is the reflected pointer value of v
			if rp.IsNil() {
				// v is a typed nil pointer
				return e.emitNil()
			} else {
				// v is a non-nil pointer; dereference it and emit that
				return e.Emit(rp.Elem().Interface())
			}
		} else if ty.Kind() == reflect.Slice {
			// Support non-`any` slices via reflection
			rv := reflect.ValueOf(v)
			err = e.emitArrayBegin(0)
			if err != nil {
				return
			}
			notFirst := false
			for i := 0; i < rv.Len(); i++ {
				av := rv.Index(i).Interface()
				if notFirst {
					err = e.emitArrayNext()
					if err != nil {
						return
					}
				}
				notFirst = true
				err = e.Emit(av)
				if err != nil {
					return
				}
			}
			return e.emitArrayEnd()
		} else if ty.Kind() == reflect.Map {
			// Support non-`any`-valued maps via reflection, as long as the key
			// type is exactly `string`
			if ty.Key() != reflect.TypeOf("") {
				return fmt.Errorf("simple json: cannot emit unsupported type %T", v)
			}

			rv := reflect.ValueOf(v)
			err = e.emitMapBegin(0)
			if err != nil {
				return
			}
			notFirst := false
			iter := rv.MapRange()
			for iter.Next() {
				key := iter.Key().String()
				value := iter.Value().Interface()
				if notFirst {
					err = e.emitMapNext()
					if err != nil {
						return
					}
				}
				notFirst = true
				err = e.emitString(key)
				if err != nil {
					return
				}
				err = e.emitMapValue()
				if err != nil {
					return
				}
				err = e.Emit(value)
				if err != nil {
					return
				}
			}
			return e.emitMapEnd()
		}
	}
	return fmt.Errorf("simple json: cannot emit unsupported type %T", v)
}

func align(n int, a int) int {
	if (n % a) == 0 {
		return n
	}
	return ((n / a) + 1) * a
}
