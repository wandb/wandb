package xdr

import (
	"encoding/binary"
	"fmt"
	"io"
	"math"
	"reflect"

	"github.com/smallfz/libnfs-go/log"
)

type Writer struct {
	base io.Writer
}

func NewWriter(w io.Writer) *Writer {
	return &Writer{base: w}
}

func (w *Writer) Write(data []byte) (int, error) {
	if i, err := w.base.Write(data); err != nil {
		log.Errorf("w.base.Write: %v", err)
		return i, err
	} else {
		return i, nil
	}
}

func (w *Writer) WriteAny(any interface{}) (int, error) {
	return w.WriteValue(reflect.ValueOf(any))
}

func (w *Writer) WriteValue(v reflect.Value) (int, error) {
	if !v.IsValid() {
		return 0, nil
	}

	vtyp := v.Type()
	kind := vtyp.Kind()

	if kind == reflect.Ptr {
		if v.IsNil() {
			return 0, nil
		}
		return w.WriteValue(v.Elem())
	}

	switch kind {
	case reflect.Bool:
		i := uint32(0)
		if v.Bool() {
			i = uint32(1)
		}
		return w.WriteUint32(i)

	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32:
		fallthrough
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32:
		i := uint32(0)
		vTo := reflect.ValueOf(&i)
		if vtyp.AssignableTo(vTo.Elem().Type()) {
			vTo.Elem().Set(v)
		} else if vtyp.ConvertibleTo(vTo.Elem().Type()) {
			vmid := v.Convert(vTo.Elem().Type())
			vTo.Elem().Set(vmid)
		} else {
			log.Errorf(
				"unable to assign %s to %s",
				vtyp.Name(), vTo.Type().Name(),
			)
			return 0, fmt.Errorf(
				"unable to assign %s to %s",
				vtyp.Name(), vTo.Type().Name(),
			)
		}
		return w.WriteUint32(i)

	case reflect.Int64, reflect.Uint64:
		i64 := uint64(0)
		vTo := reflect.ValueOf(&i64)
		if vtyp.AssignableTo(vTo.Elem().Type()) {
			vTo.Elem().Set(v)
		} else if vtyp.ConvertibleTo(vTo.Elem().Type()) {
			vmid := v.Convert(vTo.Elem().Type())
			vTo.Elem().Set(vmid)
		} else {
			log.Errorf(
				"unable to assign %s to %s",
				vtyp.Name(), vTo.Type().Name(),
			)
			return 0, fmt.Errorf(
				"unable to assign %s to %s",
				vtyp.Name(), vTo.Type().Name(),
			)
		}
		buff := make([]byte, 8)
		binary.BigEndian.PutUint64(buff, i64)
		return w.Write(buff)

	case reflect.Float32:
		i := math.Float32bits(float32(v.Float()))
		return w.WriteUint32(i)

	case reflect.Float64:
		i64 := math.Float64bits(v.Float())
		buff := make([]byte, 8)
		binary.BigEndian.PutUint64(buff, i64)
		return w.Write(buff)

	case reflect.Array:
		vElTyp := vtyp.Elem()
		cnt := v.Len()

		if cnt <= 0 {
			return 0, nil
		}

		// Special case: [n]byte
		if vElTyp.Kind() == reflect.Uint8 {
			sTyp := reflect.SliceOf(vElTyp)
			slice := reflect.MakeSlice(sTyp, v.Len(), v.Len())
			reflect.Copy(slice, v)
			dat := slice.Bytes()
			return w.WriteBytesAutoPad(dat)
		}

		sizeSent := 0
		for i := 0; i < cnt; i++ {
			vEl := v.Index(i)
			size, err := w.WriteValue(vEl)
			if err != nil {
				return sizeSent, err
			}
			sizeSent += size
		}

		return sizeSent, nil

	case reflect.Slice:
		if v.IsNil() {
			return 0, nil
		}

		vElTyp := vtyp.Elem()
		cnt := v.Len()

		sizeSent := 0
		if size, err := w.WriteUint32(uint32(cnt)); err != nil {
			return sizeSent, err
		} else {
			sizeSent += size
		}

		// Special case: []byte
		if vElTyp.Kind() == reflect.Uint8 {
			dat := v.Bytes()
			if size, err := w.WriteBytesAutoPad(dat); err != nil {
				return sizeSent, err
			} else {
				sizeSent += size
			}
			return sizeSent, nil
		}

		for i := 0; i < cnt; i++ {
			size, err := w.WriteValue(v.Index(i))
			if err != nil {
				return sizeSent, err
			}
			sizeSent += size
		}

		return sizeSent, nil

	case reflect.String:
		cnt := uint32(v.Len())
		sizeSent := 0
		if size, err := w.WriteUint32(cnt); err != nil {
			return sizeSent, err
		} else {
			sizeSent += size
		}

		dat := []byte(v.String())
		if size, err := w.WriteBytesAutoPad(dat); err != nil {
			return sizeSent, err
		} else {
			sizeSent += size
		}
		return sizeSent, nil

	case reflect.Struct:
		sizeSent := 0
		fieldCount := vtyp.NumField()
		for i := 0; i < fieldCount; i++ {
			// field := vtyp.Field(i)
			fv := v.Field(i)
			size, err := w.WriteValue(fv)
			if err != nil {
				return sizeSent, err
			}
			sizeSent += size
		}

		return sizeSent, nil

	}

	return 0, fmt.Errorf("type not supported: %s", vtyp.Name())
}

func (w *Writer) WriteBytesAutoPad(dat []byte) (int, error) {
	size := 0
	if s, err := w.Write(dat); err != nil {
		return size, err
	} else {
		size += s
	}
	padLen := Pad(len(dat))
	if padLen > 0 {
		pad := make([]byte, padLen)
		if s, err := w.Write(pad); err != nil {
			return size, err
		} else {
			size += s
		}
	}
	return size, nil
}

func (w *Writer) WriteUint32(v uint32) (int, error) {
	buff := make([]byte, 4)
	binary.BigEndian.PutUint32(buff, v)
	return w.Write(buff)
}

func (w *Writer) Flush() error {
	return nil
}
