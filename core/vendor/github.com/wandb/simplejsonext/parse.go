package simplejsonext

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"math"
	"strconv"
	"unicode/utf16"
	"unicode/utf8"
	"unsafe"
)

const (
	// Size of our read buffer for iterative i/o reading
	readBufferSize = 1024
	// We opportunistically release buffers larger than this many bytes
	oversizedBuffer = 64 * 1024
	// Maximum recursion depth for nested values
	maxDepth = 500
)

type valType int

const (
	unknownTy valType = iota
	nilTy
	boolTy
	numberTy
	stringTy
	arrayTy
	objectTy
	commaSym
	endGroupSym
)

var (
	errUnexpectedComma = errors.New("simple json: unexpected comma")
	errUnexpectedEnd   = errors.New("simple json: unexpected end of array or object")
	errLineNotEmpty    = errors.New("simple json: non-whitespace found before newline")
	errBufferNotEmpty  = errors.New("simple json: remainder of buffer not empty")
	errControlChar     = errors.New("simple json: control character, tab, or newline in string value")
	errTruncatedHex    = errors.New(
		"simple json: expected a unicode hexadecimal codepoint but json is truncated",
	)
	errMaxDepth = errors.New("simple json: maximum nesting depth exceeded")
)

type Parser interface {
	// Parse JSON from the front of the contained data as a simply-typed value
	// and return it. If the data is empty, the exact error io.EOF will be
	// returned.
	Parse() (any, error)
	// ParseObject parses JSON from the front of the contained data as a
	// simply-typed JSON object and returns it. If the JSON is a value of a type
	// other than object, an error will be returned. If the data is empty, the
	// exact error io.EOF will be returned.
	ParseObject() (map[string]any, error)
	// NextLine consumes whitespace up to the next newline, returning an error
	// if something other than whitespace exists before the next newline, or
	// returning the exact error io.EOF if the end of data is found first. This
	// method reads until exactly the next '\n' newline character, not any other
	// combination of '\r' and '\n'; it will work with "\r\n" and "\n" newlines
	// only.
	NextLine() error
	// IterLines returns a Range-func iterable for reading JSONL.
	//
	// Returns an iterable go1.22+ RangeFunc that yields each line of a JSONL
	// until the end of data. If an error occurs, it will be yielded on its own
	// and iteration will stop.
	//
	// See: https://go.dev/wiki/RangefuncExperiment
	IterLines() func(func(any, error) bool)
	// IterObjectLines returns a Range-func iterable for reading JSONL,
	// enforcing that each line must also be a JSON object rather than another
	// kind of JSON value.
	//
	// Returns an iterable go1.22+ RangeFunc that yields each line of a JSONL
	// until the end of data. If an error occurs, it will be yielded on its own
	// and iteration will stop.
	//
	// See: https://go.dev/wiki/RangefuncExperiment
	IterObjectLines() func(func(map[string]any, error) bool)
	// CheckEmpty checks that the remaining data is all whitespace, returning an
	// error if not.
	CheckEmpty() error
	// UnmarshalFull parses JSON from the front of the contained data, then
	// checks if there is any data left after. If there is, the value will still
	// be returned but there will be a "not empty" error. If the data is empty,
	// the exact error io.EOF will be returned.
	UnmarshalFull() (any, error)
	// Reset the parser with a new io.Reader.
	Reset(io.Reader)
	// ResetSlice resets the parser with a new byte slice.
	ResetSlice([]byte)
	// ResetString resets the parser with a new string.
	ResetString(string)
}

type parser struct {
	// readBuf is either the buffer where bytes are loaded from the reader, or
	// the existing in-memory slice we are parsing if we do not have a Reader.
	// This allows us to parse from a generic io.Reader just as easily as from
	// a single in-memory slice or string.
	readBuf []byte
	strBuf  bytes.Buffer // buffer used for building strings
	reader  io.Reader    // reader to load bytes from
	begin   int          // position of first unread byte in readBuf
	size    int          // position after the last byte written in readBuf
}

// NewParser creates a new parser that parses the given reader.
func NewParser(r io.Reader) Parser {
	return &parser{readBuf: make([]byte, readBufferSize), reader: r}
}

// NewParserFromSlice creates a new parser for the given slice.
func NewParserFromSlice(data []byte) Parser {
	return &parser{readBuf: data, size: len(data)}
}

// NewParserFromString creates a new parser for the given string.
func NewParserFromString(data string) Parser {
	// We unsafe-cast the string to a byte slice because we are confident that
	// nothing in our call stack will ever modify the referenced bytes.
	return &parser{
		readBuf: unsafe.Slice(unsafe.StringData(data), len(data)),
		size:    len(data),
	}
}

func (p *parser) Reset(r io.Reader) {
	if p.reader == nil {
		// Big brain: Allocate a read buffer only if we don't already have one
		p.readBuf = make([]byte, readBufferSize)
	}
	p.reader = r
	p.begin = 0
	p.size = 0
	if p.strBuf.Cap() > oversizedBuffer {
		p.strBuf = bytes.Buffer{}
	}
}

func (p *parser) ResetSlice(data []byte) {
	p.reader = nil
	p.readBuf = data
	p.begin = 0
	p.size = len(data)
	if p.strBuf.Cap() > oversizedBuffer {
		p.strBuf = bytes.Buffer{}
	}
}

func (p *parser) ResetString(data string) {
	p.reader = nil
	p.readBuf = unsafe.Slice(unsafe.StringData(data), len(data))
	p.begin = 0
	p.size = len(data)
	if p.strBuf.Cap() > oversizedBuffer {
		p.strBuf = bytes.Buffer{}
	}
}

var typeTable = [256]byte{
	'-': byte(numberTy),
	'0': byte(numberTy),
	'1': byte(numberTy),
	'2': byte(numberTy),
	'3': byte(numberTy),
	'4': byte(numberTy),
	'5': byte(numberTy),
	'6': byte(numberTy),
	'7': byte(numberTy),
	'8': byte(numberTy),
	'9': byte(numberTy),
	'"': byte(stringTy), // "..."
	'{': byte(objectTy), // {...}
	'[': byte(arrayTy),  // [...]
	'n': byte(nilTy),    // null
	't': byte(boolTy),   // true
	'f': byte(boolTy),   // false
	'I': byte(numberTy), // Infinity
	'N': byte(numberTy), // NaN
	',': byte(commaSym),
	']': byte(endGroupSym),
	'}': byte(endGroupSym),
}

const (
	notNumber      = iota
	integralNumber = 1
	floatNumber    = 2
)

var numberCharTable = [256]byte{
	'0': integralNumber,
	'1': integralNumber,
	'2': integralNumber,
	'3': integralNumber,
	'4': integralNumber,
	'5': integralNumber,
	'6': integralNumber,
	'7': integralNumber,
	'8': integralNumber,
	'9': integralNumber,
	'.': floatNumber,
	'-': integralNumber,
	'+': floatNumber,
	'e': floatNumber, // exponent
	'E': floatNumber,
	'I': floatNumber, // Infinity
	'n': floatNumber,
	'f': floatNumber,
	'i': floatNumber,
	't': floatNumber,
	'y': floatNumber,
	'N': floatNumber, // NaN
	'a': floatNumber,
}

var escapeTable = [256]byte{
	'b':  '\b',
	't':  '\t',
	'r':  '\r',
	'n':  '\n',
	'f':  '\f',
	'\\': '\\',
	'/':  '/',
	'"':  '"',
}

const notHex = 0xff

var hexTable [256]byte

func init() {
	for i := range hexTable {
		hexTable[i] = notHex
	}
	hexTable['0'] = 0x0
	hexTable['1'] = 0x1
	hexTable['2'] = 0x2
	hexTable['3'] = 0x3
	hexTable['4'] = 0x4
	hexTable['5'] = 0x5
	hexTable['6'] = 0x6
	hexTable['7'] = 0x7
	hexTable['8'] = 0x8
	hexTable['9'] = 0x9
	hexTable['a'] = 0xa
	hexTable['b'] = 0xb
	hexTable['c'] = 0xc
	hexTable['d'] = 0xd
	hexTable['e'] = 0xe
	hexTable['f'] = 0xf
	hexTable['A'] = 0xA
	hexTable['B'] = 0xB
	hexTable['C'] = 0xC
	hexTable['D'] = 0xD
	hexTable['E'] = 0xE
	hexTable['F'] = 0xF
}

// Given 4 bytes of hexadecimal text, returns the corresponding rune.
func parseHexToRune(chunk [4]byte) (r rune, err error) {
	a, b, c, d := hexTable[chunk[0]], hexTable[chunk[1]], hexTable[chunk[2]], hexTable[chunk[3]]
	if a|b|c|d == notHex {
		return 0, fmt.Errorf(
			"simple json: expected a hexadecimal unicode code point but found %#v",
			string(chunk[:]),
		)
	}
	return (rune(a) << 12) | (rune(b) << 8) | (rune(c) << 4) | (rune(d)), nil
}

func (p *parser) parseType() (t valType, err error) {
	var chunk []byte

	if err = p.skipSpaces(); err != nil {
		return
	}

	chunk, err = p.take()
	if err != nil {
		return
	}

	t = valType(typeTable[chunk[0]])
	switch t {
	case unknownTy:
		err = fmt.Errorf("simple json: expected token but found '%c'", chunk[0])
	default:
		// For all other types we don't consume anything from the stream.
		p.rewind(len(chunk))
	}

	return
}

func (p *parser) consumeNull() (err error) {
	return p.readToken(nullBytes[:])
}

func (p *parser) parseBool() (v bool, err error) {
	var b byte

	if b, err = p.peekOneByte(); err != nil {
		return
	}

	switch b {
	case falseBytes[0]:
		v, err = false, p.readToken(falseBytes[:])

	case trueBytes[0]:
		v, err = true, p.readToken(trueBytes[:])

	default:
		err = fmt.Errorf("simple json: expected boolean but found '%c'", b)
	}

	return
}

func (p *parser) parseNumber() (v any, err error) {
	p.strBuf.Reset()
	ty := integralNumber // Which kind of number we are parsing
	buffered := false    // Whether the value we're parsing is buffered
	var chunk []byte     // Current chunk we are reading
	// End result of bytes we will parse; either from a single chunk or from the
	// strBuf buffer
	var view []byte

	chunk, err = p.take()
	if err != nil {
		return
	}
ReadingChunks:
	for {
		for pos, ch := range chunk {
			switch numberCharTable[ch] {
			case integralNumber:
				// pass
			case floatNumber:
				ty = floatNumber
			case notNumber:
				// We found the end of the number
				if buffered {
					p.strBuf.Write(chunk[:pos])
					view = p.strBuf.Bytes()
				} else {
					view = chunk[:pos]
				}
				p.rewind(len(chunk) - pos)
				break ReadingChunks
			}
		}
		// We've gotten to the end of a chunk without finding a non-number
		// byte; get a new chunk
		p.strBuf.Write(chunk)
		buffered = true
		chunk, err = p.take()
		if err != nil {
			if err == io.EOF {
				view = p.strBuf.Bytes()
				break ReadingChunks
			}
			return
		}
	}

	if ty == floatNumber || checkPromoteToFloat(view) {
		// strconv.ParseFloat will work with both decimal and hexadecimal floats,
		// but we don't accept some of the characters that are required to spell a
		// hexadecimal float so effectively we only parse decimal here. We also, via
		// strconv, accept the symbols "Inf", "Infinity", and "NaN" (and negative
		// infinities).
		v, err = strconv.ParseFloat(stringNoCopy(view), 64)
		if err != nil {
			if errors.Is(err, strconv.ErrRange) {
				err = nil // When very big values overflow to infinite, we keep them
			}
		}
	} else {
		return strconv.ParseInt(stringNoCopy(view), 10, 0)
	}
	return
}

func (p *parser) parseString() (v []byte, err error) {
	var chunk []byte
	chunk, err = p.take()
	if err != nil {
		return nil, err
	}

	// Consume the initial quote
	if chunk[0] != '"' {
		return nil, fmt.Errorf("simple json: expected '\"' but found '%c'", chunk[0])
	}

	escaped := false
	chunk = chunk[1:] // Skip over the opening quote

	// There are two major cases here: A) where we find the whole string
	// already ready to go and present inside the read chunk, or B) where we
	// have to build the string's contents in strBuf, either because it needs to
	// be unescaped or because the string is too long to fit in the read buffer.
	// In case A) we will find a double quote " before a backslash \ inside the
	// first chunk we are looking at, immediately below; everything else about
	// case B) is handled after that.

	// Fast path: look for an unescaped string in the read buffer, returning a
	// slice without copying any data if possible.
	for pos, b := range chunk {
		if b == '"' {
			// We reached the end of the string
			v = chunk[:pos]                   // Value is everything until this quote
			p.rewind(len(chunk) - len(v) - 1) // consume the string and end quote
			return
		} else if b == '\\' {
			// The string has escapes in it; copy what we passed so far into
			// the buffer, not including the backslash, and start parsing from
			// there
			p.strBuf.Reset()
			p.strBuf.Write(chunk[:pos])
			// Start the escape and give back everything after this backslash
			escaped = true
			p.rewind(len(chunk) - pos - 1)
			break
		} else if b < ' ' {
			return nil, errControlChar
		}
	}

	if !escaped {
		// We read through the whole chunk but didn't find either an escape or
		// the end of the string.
		p.strBuf.Reset()
		p.strBuf.Write(chunk)
	}

	// Tracks whether we are combining a surrogate pair. If we are not, this
	// value will be zero.
	openSurrogate := rune(0)

ReadingChunks:
	for {
		chunk, err = p.take()
		if err != nil {
			return nil, err
		}
	ReadingBytes:
		for pos, b := range chunk {
			if b < ' ' {
				return nil, errControlChar
			} else if escaped {
				escaped = false
				if b == 'u' {
					// Unicode escape! This is a \u which must be followed by
					// 4 hex characters.
					// First give back our unconsumed bytes so we can use read()
					p.rewind(len(chunk) - pos - 1)
					var hexCode [4]byte
					err = p.read(hexCode[:])
					if err != nil {
						return nil, errTruncatedHex
					}
					thisRune, err := parseHexToRune(hexCode)
					if err != nil {
						return nil, err
					}
					// Handle any existing open surrogate
					if openSurrogate != 0 {
						if thisRune >= 0xdc00 && thisRune <= 0xdfff {
							// Success! This rune is a low surrogate, and both
							// the open surrogate and this current rune are
							// consumed.
							p.strBuf.WriteRune(utf16.DecodeRune(openSurrogate, thisRune))
							openSurrogate = 0
							// We gave back our chunk to use read(); fetch the
							// current chunk again from the top.
							continue ReadingChunks
						} else {
							// Previous rune was unpaired; write it now.
							p.strBuf.WriteRune(utf8.RuneError)
							openSurrogate = 0
						}
					}
					if utf16.IsSurrogate(thisRune) {
						if thisRune >= 0xdc00 {
							// This rune is an unpaired low surrogate
							p.strBuf.WriteRune(utf8.RuneError)
						} else {
							// Success! This rune is a high surrogate. Store it!
							openSurrogate = thisRune
						}
					} else {
						// This is a normal unicode-escaped rune
						p.strBuf.WriteRune(thisRune)
					}
					// We gave back our chunk to use read(); fetch the
					// current chunk again from the top.
					continue ReadingChunks
				} else {
					// Non-unicode, single-character escape. Use the LUT
					if openSurrogate != 0 {
						p.strBuf.WriteRune(utf8.RuneError)
						openSurrogate = 0
					}
					b = escapeTable[b]
					if b == 0 {
						return nil, fmt.Errorf("simple json: invalid escape %c", chunk[pos])
					}
				}
			} else if b == '\\' {
				// We aren't already looking at an escape, but we found the
				// start of one
				escaped = true
				continue ReadingBytes
			} else if b == '"' {
				// We found the end of the string!
				if openSurrogate != 0 {
					p.strBuf.WriteRune(utf8.RuneError)
				}
				// Give back everything after this end-quote.
				p.rewind(len(chunk) - pos - 1)
				break ReadingChunks // Done!
			}

			// By the time we reach here b is a (normal) non-escaped byte, or we
			// already fell through from the single-character escape case above
			// and b is already the looked-up value from the escape LUT.
			if openSurrogate != 0 {
				p.strBuf.WriteRune(utf8.RuneError)
				openSurrogate = 0
			}
			p.strBuf.WriteByte(b)
		}
	}

	return p.strBuf.Bytes(), nil
}

func (p *parser) Parse() (val any, err error) {
	return p.doParse(maxDepth)
}

func (p *parser) ParseObject() (map[string]any, error) {
	err := p.skipSpaces()
	if err != nil {
		return nil, err
	}
	return p.doParseObject(maxDepth)
}

func (p *parser) doParse(remainingDepth int) (val any, err error) {
	if remainingDepth < 0 {
		return nil, errMaxDepth
	}
	var ty valType
	ty, err = p.parseType()
	if err != nil {
		return
	}
	switch ty {
	case nilTy:
		err = p.consumeNull()
	case boolTy:
		val, err = p.parseBool()
	case numberTy:
		val, err = p.parseNumber()
	case stringTy:
		var str []byte
		str, err = p.parseString()
		// After reading strings, we always copy the bytes out as they may not
		// refer to bytes in the original buffer.
		val = string(str)
	case arrayTy:
		val, err = p.doParseArray(remainingDepth)
	case objectTy:
		val, err = p.doParseObject(remainingDepth)
	case commaSym:
		return nil, errUnexpectedComma
	case endGroupSym:
		return nil, errUnexpectedEnd
	default:
		panic("unreachable")
	}
	if err != nil {
		val = nil
	}
	return
}

func (p *parser) doParseArray(remainingDepth int) (arr []any, err error) {
	// Consume the opening bracket
	err = p.readByte('[')
	if err != nil {
		return
	}
	for {
		var ty valType
		ty, err = p.parseType()
		if err != nil {
			return
		}
		if ty == endGroupSym {
			// Found an ending brace/bracket immediately after the start of
			// the array or one of its values, cleanly ending the array
			err = p.readByte(']')
			if err != nil {
				return
			}
			break
		} else if len(arr) == 0 {
			if ty == commaSym {
				// Found a comma with no previous value
				return nil, errUnexpectedComma
			}
		} else {
			// We just read a value and the array hasn't ended. We MUST find
			// a comma next, and we have already skipped whitespace.
			err = p.readByte(',')
			if err != nil {
				return
			}
		}
		// We now have a regular following value, not an errant comma or the
		// end of the array.
		var arrVal any
		arrVal, err = p.doParse(remainingDepth - 1)
		if err != nil {
			return
		}
		arr = append(arr, arrVal)
	}
	return
}

func (p *parser) doParseObject(remainingDepth int) (obj map[string]any, err error) {
	// Consume the beginning of the object
	err = p.readByte('{')
	if err != nil {
		return nil, err
	}
	for {
		var ty valType
		ty, err = p.parseType()
		if err != nil {
			return
		}
		if ty == endGroupSym {
			// Found an ending brace/bracket immediately after the start of
			// the object or one of its items, cleanly ending the object
			err = p.readByte('}')
			if err != nil {
				return
			}
			break
		} else if obj == nil {
			if ty == commaSym {
				// Found a comma with no previous value
				return nil, errUnexpectedComma
			}
			// Initialize the object's map
			obj = make(map[string]any)
		} else {
			// We just parsed an item and the object hasn't ended. We MUST
			// find a comma next, and we have already skipped whitespace.
			err = p.readByte(',')
			if err != nil {
				return
			}
		}
		// We now have a regular following item, not an errant comma or the
		// end of the object.
		var objKeyBytes []byte
		var objVal any
		err = p.skipSpaces()
		if err != nil {
			return
		}
		// Read the map key, which MUST be a string.
		objKeyBytes, err = p.parseString()
		if err != nil {
			return
		}
		objKey := string(objKeyBytes)
		// Consume the ':' separating the key and value
		err = p.skipSpaces()
		if err != nil {
			return
		}
		err = p.readByte(':')
		if err != nil {
			return
		}
		// Read the value, which may be of any type.
		objVal, err = p.doParse(remainingDepth - 1)
		if err != nil {
			return
		}
		obj[objKey] = objVal
	}
	return
}

func (p *parser) NextLine() (err error) {
	var chunk []byte
	for {
		chunk, err = p.take()
		if err != nil {
			return
		}
		for offset, ch := range chunk {
			switch ch {
			case ' ', '\t', '\r':
				// skip
			case '\n':
				// Newline character: give back everything except the
				// whitespace we saw so far and this newline character.
				p.rewind(len(chunk) - offset - 1)
				return nil
			default:
				// Non-whitespace character: error!
				// Give back everything except the whitespace we saw so far,
				// just in case
				p.rewind(len(chunk) - offset)
				return errLineNotEmpty
			}
		}
	}
}

func (p *parser) IterLines() func(func(any, error) bool) {
	return func(yield func(any, error) bool) {
		for {
			val, err := p.Parse()
			if err == io.EOF {
				return
			}
			// Stop when we're told to or there's any error
			if !yield(val, err) || err != nil {
				return
			}
			if err := p.NextLine(); err != nil {
				if err != io.EOF {
					yield(nil, err)
				}
				return
			}
		}
	}
}

func (p *parser) IterObjectLines() func(func(map[string]any, error) bool) {
	return func(yield func(map[string]any, error) bool) {
		for {
			val, err := p.ParseObject()
			if err == io.EOF {
				return
			}
			// Stop when we're told to or there's any error
			if !yield(val, err) || err != nil {
				return
			}
			if err := p.NextLine(); err != nil {
				if err != io.EOF {
					yield(nil, err)
				}
				return
			}
		}
	}
}

func (p *parser) CheckEmpty() error {
	err := p.skipSpaces()
	if err != nil {
		return err
	}
	// After calling skipSpaces(), the buffer will ALWAYS be empty
	// (begin == size) unless non-whitespace characters were found later in the
	// data.
	if p.begin < p.size {
		return errBufferNotEmpty
	}
	return nil
}

func (p *parser) UnmarshalFull() (any, error) {
	val, err := p.Parse()
	if err != nil {
		return nil, err
	}
	return val, p.CheckEmpty()
}

// Returns the next slice of bytes available to the parser. Any bytes from the
// previous call are considered consumed unless rewind() was called. If EOF is
// reached (an expected eventual condition that doesn't indicate a hard fault),
// the error returned will be exactly io.EOF. The returned buffer will never be
// empty with a nil error.
func (p *parser) take() (buf []byte, err error) {
	// Take the remainder of the existing chunk if possible
	if p.begin < p.size {
		buf = p.readBuf[p.begin:p.size]
		p.begin = p.size
		return
	}
	buf, err = p.refreshInternal()
	p.begin = p.size
	return
}

// Fetches the next chunk into the parser. You don't want to call this function.
func (p *parser) refreshInternal() (buf []byte, err error) {
	if p.reader == nil {
		return nil, io.EOF
	}
	p.size, err = io.ReadFull(p.reader, p.readBuf)
	if p.size > 0 {
		err = nil
	} else if err == nil {
		err = io.ErrUnexpectedEOF
	}
	buf = p.readBuf[:p.size]
	return
}

// Puts n bytes from the last call to take() back to be read again by the next
// call to take().
func (p *parser) rewind(n int) {
	p.begin -= n
}

func (p *parser) peekOneByte() (byte, error) {
	if p.begin >= p.size {
		if _, err := p.refreshInternal(); err != nil {
			return 0, err
		}
		p.begin = 0
	}
	return p.readBuf[p.begin], nil
}

func (p *parser) readByte(b byte) error {
	actual, err := p.peekOneByte()
	if err != nil {
		return err
	}
	if actual != b {
		return fmt.Errorf("simple json: expected '%c' but found '%c'", b, actual)
	}
	p.begin++ // it is safe to advance exactly one byte after peeking 1
	return nil
}

// Read exactly enough bytes to fill the given slice or error out.
func (p *parser) read(fillThis []byte) error {
	// Repeatedly fill the destination buffer until it's full
	for {
		chunk, err := p.take()
		if err != nil {
			return err
		}
		copied := copy(fillThis, chunk)
		if len(chunk) >= len(fillThis) {
			p.rewind(len(chunk) - len(fillThis))
			return nil
		}
		fillThis = fillThis[copied:]
	}
}

// Consumes an exact token from the parser, returning an error if anything else
// was found.
func (p *parser) readToken(token []byte) error {
	actual := make([]byte, len(token))
	err := p.read(actual)
	if err != nil {
		return err
	}
	if !bytes.Equal(token, actual) {
		return fmt.Errorf("simple json: expected %#v but found %#v", string(token), string(actual))
	}
	return nil
}

func (p *parser) skipSpaces() (err error) {
	var chunk []byte
	for {
		chunk, err = p.take()
		if err != nil {
			if err == io.EOF {
				return nil
			}
			return
		}
		for offset, ch := range chunk {
			switch ch {
			case ' ', '\n', '\t', '\r':
				// skip
			default:
				// Non-whitespace character: give back everything except the
				// whitespace we saw so far.
				p.rewind(len(chunk) - offset)
				return nil
			}
		}
	}
}

// Unsafely casts a byte slice to a string. Only used internally, when we are
// confident that the bytes will not be modified while the string value is in
// use.
func stringNoCopy(b []byte) (view string) {
	if len(b) == 0 {
		return ""
	}
	return unsafe.String(unsafe.SliceData(b), len(b))
}

// []byte("9223372036854775807"), int64_max as text
var int64MaxTextBytes = []byte(strconv.Itoa(math.MaxInt64))

// []byte("-9223372036854775808"), int64_min as text
var int64MinTextBytes = []byte(strconv.Itoa(math.MinInt64))

func checkPromoteToFloat(b []byte) bool {
	if len(b) == 0 {
		return false
	}

	compare := &int64MaxTextBytes
	if b[0] == '-' {
		compare = &int64MinTextBytes
	}

	if len(b) < len(*compare) {
		return false
	}
	if len(b) > len(*compare) {
		return true
	}
	return bytes.Compare(b, *compare) > 0
}
