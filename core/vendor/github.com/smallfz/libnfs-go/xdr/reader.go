package xdr

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math"
	"reflect"
)

// int32, uint32, int, bool => xdr.b4
// int64, uint64 => xdr.b8
// float32 => xdr.b4, IEEE
// float64 => xdr.b8, IEEE

//
// opaque identifier[n]
//   [bytes * n...] + PAD
//

// opaque identifier<>
//  or opaque identifier<max>
//  or opaque identifier<1024>
//
//   [uint32:length][bytes...] + PAD

// string object<>
//  or string object<max>
//
//   [uint32:length][bytes...] + PAD

//
// fixed-length Array:
//   type-name identifier[n]
//
//   [element * n]

// var-length Array:
//   type-name identifier<>
//   type-name identifier<max>
//
//   [uint32:count][element * n]

// structure, struct
//   struct{
//     field a;
//     field b;
//   }
//
//   [a][b]
//

// optional data
//   type-name *identifier
//
// like var-length array with max size 1.

type Reader struct {
	r io.Reader
}

func NewReader(base io.Reader) *Reader {
	return &Reader{r: base}
}

func (r *Reader) Debugf(t string, args ...interface{}) {
	// log.Debugf(t, args...)
}

func (r *Reader) ReadBytes(size int) ([]byte, error) {
	buf := make([]byte, size)
	if _, err := io.ReadFull(r.r, buf); err != nil {
		return nil, err
	}
	return buf, nil
}

func (r *Reader) Read(buf []byte) (int, error) {
	if n, err := io.ReadFull(r.r, buf); err != nil {
		return 0, err
	} else {
		return n, nil
	}
}

func (r *Reader) ReadUint32() (uint32, error) {
	buff, err := r.ReadBytes(4)
	if err != nil {
		return 0, err
	}
	return binary.BigEndian.Uint32(buff), nil
}

func (r *Reader) ReadValue(v reflect.Value) (int, error) {
	if !v.IsValid() {
		return 0, errors.New("invalid target")
	}

	kind := v.Kind()
	if kind != reflect.Ptr {
		return 0, errors.New("ReadAs: expects a ptr target")
	}

	kind = v.Elem().Kind()

	switch kind {
	case reflect.Ptr:
		ev := v.Elem()
		if ev.IsNil() {
			ev.Set(reflect.New(ev.Type().Elem()))
		}
		if size, err := r.ReadValue(ev); err != nil {
			return 0, err
		} else {
			return size, nil
		}

	case reflect.Bool:
		// todo: convert to xdr.b4
		if iv, err := r.ReadUint32(); err != nil {
			return 0, err
		} else {
			if iv > 0 {
				v.Elem().SetBool(true)
			} else {
				v.Elem().SetBool(false)
			}
			return 4, nil
		}

	case reflect.Float32:
		if iv, err := r.ReadUint32(); err != nil {
			return 0, err
		} else {
			fv := math.Float32frombits(iv)
			v.Elem().Set(reflect.ValueOf(fv))
			return 4, nil
		}

	case reflect.Float64:
		if buff, err := r.ReadBytes(8); err != nil {
			return 0, err
		} else {
			iv := binary.BigEndian.Uint64(buff)
			fv := math.Float64frombits(iv)
			v.Elem().SetFloat(fv)
			return len(buff), nil
		}

	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32:
		fallthrough
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32:
		size := 4
		buff, err := r.ReadBytes(size)
		if err != nil {
			return size, err
		}
		iv := uint64(binary.BigEndian.Uint32(buff))
		vFrom := reflect.ValueOf(iv)
		vTo := v.Elem()
		if vFrom.Type().AssignableTo(vTo.Type()) {
			v.Elem().SetUint(iv)
			return size, nil
		} else if vFrom.Type().ConvertibleTo(vTo.Type()) {
			v1 := vFrom.Convert(vTo.Type())
			v.Elem().Set(v1)
			return size, nil
		}
		return size, fmt.Errorf("unable to assign %T to %s", iv, kind)

	case reflect.Int64, reflect.Uint64:
		// todo: convert to xdr.b8
		size := 8
		buff, err := r.ReadBytes(size)
		if err != nil {
			return size, err
		}
		iv := binary.BigEndian.Uint64(buff)
		vFrom := reflect.ValueOf(iv)
		vTo := v.Elem()
		if vFrom.Type().AssignableTo(vTo.Type()) {
			v.Elem().SetUint(iv)
			return size, nil
		} else if vFrom.Type().ConvertibleTo(vTo.Type()) {
			v1 := vFrom.Convert(vTo.Type())
			v.Elem().Set(v1)
			return size, nil
		}
		return size, fmt.Errorf("unable to assign %T to %s", iv, kind)

	case reflect.Array:
		// fixed length array
		sizeConsumed := 0
		vtyp := v.Elem().Type()
		arrLen := vtyp.Len()
		varr := reflect.New(vtyp)

		// Special case: [n]byte
		if vtyp.Elem().Kind() == reflect.Uint8 {
			padLen := Pad(arrLen)
			dat, err := r.ReadBytes(arrLen + padLen)
			if err != nil {
				return sizeConsumed, err
			}
			sizeConsumed += len(dat)
			dat = dat[:arrLen]
			for i, bv := range dat {
				v.Elem().Index(i).Set(reflect.ValueOf(bv))
			}
			return sizeConsumed, nil
		}

		for i := 0; i < arrLen; i++ {
			// todo: read an element
			item := reflect.New(vtyp.Elem())
			if size, err := r.ReadValue(item); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}
			v1 := varr.Elem().Index(i)
			v1.Set(item.Elem())
		}
		v.Elem().Set(varr.Elem())
		return sizeConsumed, nil

	case reflect.Slice:
		sizeConsumed := 0
		arrLen32, err := r.ReadUint32()
		if err != nil {
			return 0, err
		} else {
			sizeConsumed += 4
		}

		arrLen := int(arrLen32)
		vtyp := v.Elem().Type()

		// Special case: []byte
		if vtyp.Elem().Kind() == reflect.Uint8 {
			padLen := Pad(arrLen)
			r.Debugf(
				"[]byte: len=%d, len-with-pad=%d",
				arrLen, arrLen+padLen,
			)
			dat, err := r.ReadBytes(arrLen + padLen)
			if err != nil {
				return sizeConsumed, err
			}
			sizeConsumed += len(dat)
			dat = dat[:arrLen]
			v.Elem().SetBytes(dat)
			return sizeConsumed, nil
		}

		varr := reflect.MakeSlice(vtyp, arrLen, arrLen)
		for i := 0; i < arrLen; i++ {
			// read an element
			item := reflect.New(vtyp.Elem())
			if size, err := r.ReadValue(item); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}
			v1 := varr.Index(i)
			v1.Set(item.Elem())
		}
		v.Elem().Set(varr)

		return sizeConsumed, nil

	case reflect.String:
		sizeConsumed := 0
		sLen32, err := r.ReadUint32()
		if err != nil {
			return 0, err
		} else {
			sizeConsumed += 4
		}

		sLen := int(sLen32)
		padLen := Pad(sLen)

		dat, err := r.ReadBytes(sLen + padLen)
		if err != nil {
			return sizeConsumed, err
		}
		sizeConsumed += len(dat)
		dat = dat[:sLen]
		r.Debugf("size: %d", sLen32)
		r.Debugf("string: %v", dat)
		v.Elem().SetString(string(dat))
		return sizeConsumed, nil

	case reflect.Struct:
		sizeConsumed := 0
		vtyp := v.Elem().Type()
		fieldCount := vtyp.NumField()
		for i := 0; i < fieldCount; i++ {
			field := vtyp.Field(i)
			fv := v.Elem().Field(i)
			r.Debugf(" - field: %s", field.Name)
			pToFv := fv.Addr()

			switch fv.Type().Kind() {
			case reflect.Slice:
				if fv.IsNil() {
					pToFv = reflect.New(fv.Type())
				}
			}

			if size, err := r.ReadValue(pToFv); err != nil {
				return sizeConsumed, fmt.Errorf(
					"ReadValue(field:%s): %v", field.Name, err,
				)
			} else {
				fv.Set(pToFv.Elem())
				sizeConsumed += size
			}
		}
		return sizeConsumed, nil

	default:
		return 0, fmt.Errorf("type not supported: %s", kind)
	}
}

func (r *Reader) ReadAs(target interface{}) (int, error) {
	v := reflect.ValueOf(target)
	return r.ReadValue(v)
}
