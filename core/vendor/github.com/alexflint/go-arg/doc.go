// Package arg parses command line arguments using the fields from a struct.
//
// For example,
//
//	var args struct {
//		Iter int
//		Debug bool
//	}
//	arg.MustParse(&args)
//
// defines two command line arguments, which can be set using any of
//
//	./example --iter=1 --debug  // debug is a boolean flag so its value is set to true
//	./example -iter 1           // debug defaults to its zero value (false)
//	./example --debug=true      // iter defaults to its zero value (zero)
//
// The fastest way to see how to use go-arg is to read the examples below.
//
// Fields can be bool, string, any float type, or any signed or unsigned integer type.
// They can also be slices of any of the above, or slices of pointers to any of the above.
//
// Tags can be specified using the `arg` and `help` tag names:
//
//	var args struct {
//		Input string   `arg:"positional"`
//		Log string     `arg:"positional,required"`
//		Debug bool     `arg:"-d" help:"turn on debug mode"`
//		RealMode bool  `arg:"--real"
//		Wr io.Writer   `arg:"-"`
//	}
//
// Any tag string that starts with a single hyphen is the short form for an argument
// (e.g. `./example -d`), and any tag string that starts with two hyphens is the long
// form for the argument (instead of the field name).
//
// Other valid tag strings are `positional` and `required`.
//
// Fields can be excluded from processing with `arg:"-"`.
package arg
