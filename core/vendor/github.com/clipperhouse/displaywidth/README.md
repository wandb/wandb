# displaywidth

A high-performance Go package for measuring the monospace display width of strings, UTF-8 bytes, and runes.

[![Documentation](https://pkg.go.dev/badge/github.com/clipperhouse/displaywidth.svg)](https://pkg.go.dev/github.com/clipperhouse/displaywidth)
[![Test](https://github.com/clipperhouse/displaywidth/actions/workflows/gotest.yml/badge.svg)](https://github.com/clipperhouse/displaywidth/actions/workflows/gotest.yml)
[![Fuzz](https://github.com/clipperhouse/displaywidth/actions/workflows/gofuzz.yml/badge.svg)](https://github.com/clipperhouse/displaywidth/actions/workflows/gofuzz.yml)

## Install
```bash
go get github.com/clipperhouse/displaywidth
```

## Usage

```go
package main

import (
    "fmt"
    "github.com/clipperhouse/displaywidth"
)

func main() {
    width := displaywidth.String("Hello, 世界!")
    fmt.Println(width)

    width = displaywidth.Bytes([]byte("🌍"))
    fmt.Println(width)

    width = displaywidth.Rune('🌍')
    fmt.Println(width)
}
```

For most purposes, you should use the `String` or `Bytes` methods. They sum
the widths of grapheme clusters in the string or byte slice.

> Note: in your application, iterating over runes to measure width is likely incorrect;
the smallest unit of display is a grapheme, not a rune.

### Iterating over graphemes

If you need the individual graphemes:

```go
import (
    "fmt"
    "github.com/clipperhouse/displaywidth"
)

func main() {
    g := displaywidth.StringGraphemes("Hello, 世界!")
    for g.Next() {
        width := g.Width()
        value := g.Value()
        // do something with the width or value
    }
}
```

### Options

There is one option, `displaywidth.Options.EastAsianWidth`, which defines
how [East Asian Ambiguous characters](https://www.unicode.org/reports/tr11/#Ambiguous)
are treated.

When `false` (default), East Asian Ambiguous characters are treated as width 1.
When `true`, they are treated as width 2.

You may wish to configure this based on environment variables or locale.
 `go-runewidth`, for example, does so
 [during package initialization](https://github.com/mattn/go-runewidth/blob/master/runewidth.go#L26C1-L45C2).

`displaywidth` does not do this automatically, we prefer to leave it to you.
You might do something like:

```go
var width displaywidth.Options // zero value is default

func init() {
    if os.Getenv("EAST_ASIAN_WIDTH") == "true" {
        width = displaywidth.Options{EastAsianWidth: true}
    }
    // or check locale, or any other logic you want
}

// use it in your logic
func myApp() {
    fmt.Println(width.String("Hello, 世界!"))
}
```

## Technical standards and compatibility

This package implements the Unicode East Asian Width standard
([UAX #11](https://www.unicode.org/reports/tr11/tr11-43.html)), and handles
[version selectors](https://en.wikipedia.org/wiki/Variation_Selectors_(Unicode_block)),
and [regional indicator pairs](https://en.wikipedia.org/wiki/Regional_indicator_symbol)
(flags). We implement [Unicode TR51](https://www.unicode.org/reports/tr51/tr51-27.html). We are keeping
an eye on [emerging standards](https://www.jeffquast.com/post/state-of-terminal-emulation-2025/).


`clipperhouse/displaywidth`, `mattn/go-runewidth`, and `rivo/uniseg` will
give the same outputs for most real-world text. Extensive details are in the
[compatibility analysis](comparison/COMPATIBILITY_ANALYSIS.md).

If you wish to investigate the core logic, see the `lookupProperties` and `width`
functions in [width.go](width.go#L139). The essential trie generation logic is in
`buildPropertyBitmap` in [unicode.go](internal/gen/unicode.go#L316).


## Prior Art

[mattn/go-runewidth](https://github.com/mattn/go-runewidth)

[rivo/uniseg](https://github.com/rivo/uniseg)

[x/text/width](https://pkg.go.dev/golang.org/x/text/width)

[x/text/internal/triegen](https://pkg.go.dev/golang.org/x/text/internal/triegen)

## Benchmarks

```bash
cd comparison
go test -bench=. -benchmem
```

```
goos: darwin
goarch: arm64
pkg: github.com/clipperhouse/displaywidth/comparison
cpu: Apple M2

BenchmarkString_Mixed/clipperhouse/displaywidth-8      	     10326 ns/op	   163.37 MB/s	      0 B/op	    0 allocs/op
BenchmarkString_Mixed/mattn/go-runewidth-8             	     14415 ns/op	   117.03 MB/s	      0 B/op	    0 allocs/op
BenchmarkString_Mixed/rivo/uniseg-8                    	     19343 ns/op	    87.21 MB/s	      0 B/op	    0 allocs/op

BenchmarkString_EastAsian/clipperhouse/displaywidth-8  	     10561 ns/op	   159.74 MB/s	      0 B/op	    0 allocs/op
BenchmarkString_EastAsian/mattn/go-runewidth-8         	     23790 ns/op	    70.91 MB/s	      0 B/op	    0 allocs/op
BenchmarkString_EastAsian/rivo/uniseg-8                	     19322 ns/op	    87.31 MB/s	      0 B/op	    0 allocs/op

BenchmarkString_ASCII/clipperhouse/displaywidth-8      	      1033 ns/op	   123.88 MB/s	      0 B/op	    0 allocs/op
BenchmarkString_ASCII/mattn/go-runewidth-8             	      1168 ns/op	   109.59 MB/s	      0 B/op	    0 allocs/op
BenchmarkString_ASCII/rivo/uniseg-8                    	      1585 ns/op	    80.74 MB/s	      0 B/op	    0 allocs/op

BenchmarkString_Emoji/clipperhouse/displaywidth-8      	      3034 ns/op	   238.61 MB/s	      0 B/op	    0 allocs/op
BenchmarkString_Emoji/mattn/go-runewidth-8             	      4797 ns/op	   150.94 MB/s	      0 B/op	    0 allocs/op
BenchmarkString_Emoji/rivo/uniseg-8                    	      6612 ns/op	   109.50 MB/s	      0 B/op	    0 allocs/op

BenchmarkRune_Mixed/clipperhouse/displaywidth-8        	      3343 ns/op	   504.67 MB/s	      0 B/op	    0 allocs/op
BenchmarkRune_Mixed/mattn/go-runewidth-8               	      5414 ns/op	   311.62 MB/s	      0 B/op	    0 allocs/op

BenchmarkRune_EastAsian/clipperhouse/displaywidth-8    	      3393 ns/op	   497.17 MB/s	      0 B/op	    0 allocs/op
BenchmarkRune_EastAsian/mattn/go-runewidth-8           	     15312 ns/op	   110.17 MB/s	      0 B/op	    0 allocs/op

BenchmarkRune_ASCII/clipperhouse/displaywidth-8        	       256.9 ns/op	   498.32 MB/s	      0 B/op	    0 allocs/op
BenchmarkRune_ASCII/mattn/go-runewidth-8               	       265.7 ns/op	   481.75 MB/s	      0 B/op	    0 allocs/op

BenchmarkRune_Emoji/clipperhouse/displaywidth-8        	      1336 ns/op	   541.96 MB/s	      0 B/op	    0 allocs/op
BenchmarkRune_Emoji/mattn/go-runewidth-8               	      2304 ns/op	   314.23 MB/s	      0 B/op	    0 allocs/op
```

Here are some notes on [how to make Unicode things fast](https://clipperhouse.com/go-unicode/).
