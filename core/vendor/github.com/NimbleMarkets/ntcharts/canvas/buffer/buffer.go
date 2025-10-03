// ntcharts - Copyright (c) 2024 Neomantra Corp.

// Package buffer contain buffers used with charts.
package buffer

import (
	"github.com/NimbleMarkets/ntcharts/canvas"
)

// Float64ScaleBuffer is a variable size buffer
// that stores float64 data values and a scaled version of the data.
// Scaling is done by multiplying incoming values
// by a constant scale factor.
type Float64ScaleBuffer struct {
	buf    []float64 // original data
	sbuf   []float64 // scaled data
	offset float64   // offset to subtract
	scale  float64   // scaling factor
}

// NewFloat64ScaleBuffer returns *Float64ScaleBuffer initialized to default settings.
func NewFloat64ScaleBuffer(o, sc float64) *Float64ScaleBuffer {
	return &Float64ScaleBuffer{
		buf:    []float64{},
		sbuf:   []float64{},
		offset: o,
		scale:  sc,
	}
}

// Clear resets buffer contents.
func (b *Float64ScaleBuffer) Clear() {
	b.buf = []float64{}
	b.sbuf = []float64{}
}

// Length returns number of data in buffer.
func (b *Float64ScaleBuffer) Length() int {
	return len(b.buf)
}

// Scale returns scaling factor.
func (b *Float64ScaleBuffer) Scale() float64 {
	return b.scale
}

// ScaleDatum returns a scaled float64 using
// internal buffer scaling from a given float64.
func (b *Float64ScaleBuffer) ScaleDatum(f float64) float64 {
	return (f - b.offset) * b.scale
}

// SetScale updates scaling factor and recomputes all scaled data.
func (b *Float64ScaleBuffer) SetScale(sc float64) {
	b.scale = sc
	b.sbuf = make([]float64, 0, len(b.buf))
	for _, v := range b.buf {
		b.sbuf = append(b.sbuf, b.ScaleDatum(v))
	}
}

// Offset returns data value offset.
func (b *Float64ScaleBuffer) Offset() float64 {
	return b.offset
}

// SetOffset updates offset and recomputes all scaled data.
func (b *Float64ScaleBuffer) SetOffset(o float64) {
	b.offset = o
	b.sbuf = make([]float64, 0, len(b.buf))
	for _, v := range b.buf {
		b.sbuf = append(b.sbuf, b.ScaleDatum(v))
	}
}

// Push adds Float64Point data to the back of the buffer.
func (b *Float64ScaleBuffer) Push(p float64) {
	b.buf = append(b.buf, p)
	b.sbuf = append(b.sbuf, b.ScaleDatum(p))
}

// Pop erases the oldest Float64Point from the buffer.
func (b *Float64ScaleBuffer) Pop() {
	b.buf = b.buf[1:]
	b.sbuf = b.sbuf[1:]
}

// SetData sets contents of internal buffer
// to given []float64 and scales the data.
func (b *Float64ScaleBuffer) SetData(d []float64) {
	b.buf = make([]float64, 0, len(d))
	b.sbuf = make([]float64, 0, len(d))
	for _, p := range d {
		b.buf = append(b.buf, p)
		b.sbuf = append(b.sbuf, b.ScaleDatum(p))
	}
}

// ReadAll returns entire scaled data buffer.
func (b *Float64ScaleBuffer) ReadAll() []float64 {
	return b.sbuf
}

// ReadAllRaw returns entire original data buffer.
func (b *Float64ScaleBuffer) ReadAllRaw() []float64 {
	return b.buf
}

// At returns Float64Point of scaled data at index i of buffer.
func (b *Float64ScaleBuffer) At(i int) float64 {
	return b.sbuf[i]
}

// AtRaw returns Float64Point of original data at index i of buffer.
func (b *Float64ScaleBuffer) AtRaw(i int) float64 {
	return b.buf[i]
}

// Float64ScaleRingBuffer is a fix-sized ring buffer
// that stores float64 data values and a scaled version of the data.
// Scaling is done by first subtracting by the offset and then multiplying
// incoming values by a constant scale factor.
// Unlike traditional ring buffers, pushing data to the buffer
// while at full capacity will erase the oldest datum
// from the buffer to create room for writing.
type Float64ScaleRingBuffer struct {
	buf    []float64 // original data
	sbuf   []float64 // scaled data
	offset float64   // offset to subtract
	scale  float64   // scaling factor

	length int // number of elements
	sz     int // capacitiy

	wIdx int // write index
	rIdx int // read index
}

// NewFloat64ScaleRingBuffer returns *Float64ScaleRingBuffer initialized to default settings.
func NewFloat64ScaleRingBuffer(s int, o, sc float64) *Float64ScaleRingBuffer {
	return &Float64ScaleRingBuffer{
		buf:    make([]float64, s),
		sbuf:   make([]float64, s),
		offset: o,
		scale:  sc,
		sz:     s,
		wIdx:   0,
		rIdx:   0}
}

// Clear resets buffer contents.
func (b *Float64ScaleRingBuffer) Clear() {
	b.length = 0
	b.wIdx = 0
	b.rIdx = 0
}

// Length returns number of data in buffer.
func (b *Float64ScaleRingBuffer) Length() int {
	return b.length
}

// Size returns buffer capacity.
func (b *Float64ScaleRingBuffer) Size() int {
	return b.sz
}

// Scale returns scaling factor.
func (b *Float64ScaleRingBuffer) Scale() float64 {
	return b.scale
}

// ScaleDatum returns a scaled float64 using
// internal buffer scaling from a given float64.
func (b *Float64ScaleRingBuffer) ScaleDatum(f float64) float64 {
	return (f - b.offset) * b.scale
}

// SetScale updates scaling factor and recomputes all scaled data.
func (b *Float64ScaleRingBuffer) SetScale(sc float64) {
	b.scale = sc
	for i, v := range b.buf {
		b.sbuf[i] = b.ScaleDatum(v)
	}
}

// Offset returns data value offset.
func (b *Float64ScaleRingBuffer) Offset() float64 {
	return b.offset
}

// SetOffset updates offset and recomputes all scaled data.
func (b *Float64ScaleRingBuffer) SetOffset(o float64) {
	b.offset = o
	for i, v := range b.buf {
		b.sbuf[i] = b.ScaleDatum(v)
	}
}

// Push adds float64 data to the back of the buffer.
func (b *Float64ScaleRingBuffer) Push(f float64) {
	b.buf[b.wIdx] = f
	b.sbuf[b.wIdx] = b.ScaleDatum(f)
	b.wIdx++
	if b.wIdx >= b.sz {
		b.wIdx = 0
	}
	if b.length == b.sz { // on full buffer, just increment read index
		b.rIdx++
		if b.rIdx >= b.sz {
			b.rIdx = 0
		}
	} else {
		b.length++
	}
}

// Pop erases the oldest float64 from the buffer.
func (b *Float64ScaleRingBuffer) Pop() {
	b.rIdx++
	if b.rIdx >= b.sz {
		b.rIdx = 0
	}
	b.length--
}

// ReadAll returns entire scaled data buffer.
func (b *Float64ScaleRingBuffer) ReadAll() []float64 {
	return b.getBuffer(b.sbuf)
}

// ReadAllRaw returns entire original data buffer.
func (b *Float64ScaleRingBuffer) ReadAllRaw() []float64 {
	return b.getBuffer(b.buf)
}

func (b *Float64ScaleRingBuffer) getBuffer(buf []float64) (f []float64) {
	sz := b.sz
	ln := b.length
	idx := b.rIdx

	f = make([]float64, 0, sz)
	for i := 0; i < ln; i++ {
		f = append(f, buf[idx])
		idx++
		if idx >= sz {
			idx = 0
		}
	}
	return
}

// Float64PointScaleBuffer is a variable size buffer
// that stores Float64Points and a scaled version of the Float64Points.
// Scaling is done by multiplying incoming values (X,Y) coordinates
// by a constant scale factor.
type Float64PointScaleBuffer struct {
	buf     []canvas.Float64Point // original data
	sbuf    []canvas.Float64Point // scaled data
	offsetP canvas.Float64Point   // offset to subtract X,Y values from
	scale   canvas.Float64Point   // scaling factor for X,Y values
}

// NewFloat64PointScaleBuffer returns *Float64PointScaleBuffer initialized to default settings.
func NewFloat64PointScaleBuffer(o, sc canvas.Float64Point) *Float64PointScaleBuffer {
	return &Float64PointScaleBuffer{
		buf:     []canvas.Float64Point{},
		sbuf:    []canvas.Float64Point{},
		offsetP: o,
		scale:   sc,
	}
}

// Clear resets buffer contents.
func (b *Float64PointScaleBuffer) Clear() {
	b.buf = []canvas.Float64Point{}
	b.sbuf = []canvas.Float64Point{}
}

// Length returns number of data in buffer.
func (b *Float64PointScaleBuffer) Length() int {
	return len(b.buf)
}

// Scale returns Float64Point used to multiple data points by.
func (b *Float64PointScaleBuffer) Scale() canvas.Float64Point {
	return b.scale
}

// ScaleDatum returns a scaled Float64Point using
// internal buffer scaling from a given Float64Point.
func (b *Float64PointScaleBuffer) ScaleDatum(f canvas.Float64Point) canvas.Float64Point {
	return f.Sub(b.offsetP).Mul(b.scale)
}

// SetScale updates scaling factor and recomputes all scaled data.
func (b *Float64PointScaleBuffer) SetScale(sc canvas.Float64Point) {
	b.scale = sc
	b.sbuf = make([]canvas.Float64Point, 0, len(b.buf))
	for _, v := range b.buf {
		b.sbuf = append(b.sbuf, b.ScaleDatum(v))
	}
}

// Offset returns Float64Point used to subtract data points from.
func (b *Float64PointScaleBuffer) Offset() canvas.Float64Point {
	return b.scale
}

// SetOffset updates offsets and recomputes all scaled data.
func (b *Float64PointScaleBuffer) SetOffset(o canvas.Float64Point) {
	b.offsetP = o
	b.sbuf = make([]canvas.Float64Point, 0, len(b.buf))
	for _, v := range b.buf {
		b.sbuf = append(b.sbuf, b.ScaleDatum(v))
	}
}

// Push adds Float64Point data to the back of the buffer.
func (b *Float64PointScaleBuffer) Push(p canvas.Float64Point) {
	b.buf = append(b.buf, p)
	b.sbuf = append(b.sbuf, b.ScaleDatum(p))
}

// Pop erases the oldest Float64Point from the buffer.
func (b *Float64PointScaleBuffer) Pop() {
	b.buf = b.buf[1:]
	b.sbuf = b.sbuf[1:]
}

// SetData sets contents of internal buffer
// to given []float64 and scales the data.
func (b *Float64PointScaleBuffer) SetData(d []canvas.Float64Point) {
	b.buf = make([]canvas.Float64Point, 0, len(d))
	b.sbuf = make([]canvas.Float64Point, 0, len(d))
	for _, p := range d {
		b.buf = append(b.buf, p)
		b.sbuf = append(b.sbuf, b.ScaleDatum(p))
	}
}

// ReadAll returns entire scaled data buffer.
func (b *Float64PointScaleBuffer) ReadAll() []canvas.Float64Point {
	return b.sbuf
}

// ReadAllRaw returns entire original data buffer.
func (b *Float64PointScaleBuffer) ReadAllRaw() []canvas.Float64Point {
	return b.buf
}

// At returns Float64Point of scaled data at index i of buffer.
func (b *Float64PointScaleBuffer) At(i int) canvas.Float64Point {
	return b.sbuf[i]
}

// AtRaw returns Float64Point of original data at index i of buffer.
func (b *Float64PointScaleBuffer) AtRaw(i int) canvas.Float64Point {
	return b.buf[i]
}
