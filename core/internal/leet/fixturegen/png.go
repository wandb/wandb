package main

// Deterministic PNG encoding.
//
// The standard image/png encoder is deterministic for a fixed Go toolchain,
// but its compressed output is not contractually stable across Go versions.
// Fixture PNGs must be byte-identical forever, so this file hand-rolls a
// minimal PNG writer that uses zlib "stored" (uncompressed) deflate blocks.
// Every byte of the output is a pure function of the pixel data.

import (
	"bytes"
	"hash/adler32"
	"hash/crc32"
)

// encodePNG encodes an 8-bit RGB image. pix returns the color at (x, y).
func encodePNG(width, height int, pix func(x, y int) [3]byte) []byte {
	// Raw scanlines: each row is a filter byte (0 = None) plus RGB triples.
	raw := make([]byte, 0, (1+3*width)*height)
	for y := range height {
		raw = append(raw, 0)
		for x := range width {
			c := pix(x, y)
			raw = append(raw, c[0], c[1], c[2])
		}
	}

	var b bytes.Buffer
	b.Write([]byte{0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'})

	ihdr := make([]byte, 13)
	putU32BE(ihdr[0:4], uint32(width))
	putU32BE(ihdr[4:8], uint32(height))
	ihdr[8] = 8  // bit depth
	ihdr[9] = 2  // color type: truecolor RGB
	ihdr[10] = 0 // compression
	ihdr[11] = 0 // filter
	ihdr[12] = 0 // interlace
	writePNGChunk(&b, "IHDR", ihdr)
	writePNGChunk(&b, "IDAT", zlibStored(raw))
	writePNGChunk(&b, "IEND", nil)
	return b.Bytes()
}

func writePNGChunk(b *bytes.Buffer, typ string, data []byte) {
	var u [4]byte
	putU32BE(u[:], uint32(len(data)))
	b.Write(u[:])
	b.WriteString(typ)
	b.Write(data)

	crc := crc32.NewIEEE()
	_, _ = crc.Write([]byte(typ))
	_, _ = crc.Write(data)
	putU32BE(u[:], crc.Sum32())
	b.Write(u[:])
}

// zlibStored wraps raw in a zlib stream of stored (uncompressed) deflate
// blocks: 2-byte zlib header, stored blocks, and a big-endian adler32.
func zlibStored(raw []byte) []byte {
	out := make([]byte, 0, len(raw)+16)
	out = append(out, 0x78, 0x01) // zlib header: 32K window, fastest

	i := 0
	for {
		n := min(len(raw)-i, 65535)
		final := byte(0)
		if i+n == len(raw) {
			final = 1
		}
		nlen := ^uint16(n)
		out = append(out, final, byte(n), byte(n>>8), byte(nlen), byte(nlen>>8))
		out = append(out, raw[i:i+n]...)
		i += n
		if final == 1 {
			break
		}
	}

	a := adler32.Checksum(raw)
	out = append(out, byte(a>>24), byte(a>>16), byte(a>>8), byte(a))
	return out
}

func putU32BE(b []byte, v uint32) {
	b[0] = byte(v >> 24)
	b[1] = byte(v >> 16)
	b[2] = byte(v >> 8)
	b[3] = byte(v)
}
