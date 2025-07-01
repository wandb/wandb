package pfxout

import (
	"fmt"
)

type Formatter struct {
	prefix string
}

func New(prefix string) *Formatter {
	return &Formatter{
		prefix: prefix,
	}
}

// Print formats and prints the given text to the output using the prefix
func (pf *Formatter) Print(text string) {
	if pf.prefix == "" {
		fmt.Printf("%v", text)
	} else {
		fmt.Printf("%v: %v", pf.prefix, text)
	}
}

func (pf *Formatter) Println(text string) {
	pf.Print(text + "\n")
}

// WithColor adds a color to the string.
func WithColor(str string, color Color) string {
	return fmt.Sprintf("%v%v%v", color, str, resetFormat)
}

// WithStyle adds a style to the string.
func WithStyle(str string, style Style) string {
	return fmt.Sprintf("%v%v%v", style, str, resetFormat)
}
