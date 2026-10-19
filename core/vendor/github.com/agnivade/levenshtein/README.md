levenshtein ![Build Status](https://github.com/agnivade/levenshtein/actions/workflows/ci.yml/badge.svg) [![Go Report Card](https://goreportcard.com/badge/github.com/agnivade/levenshtein)](https://goreportcard.com/report/github.com/agnivade/levenshtein) [![PkgGoDev](https://pkg.go.dev/badge/github.com/agnivade/levenshtein)](https://pkg.go.dev/github.com/agnivade/levenshtein)
===========

[Go](http://golang.org) package to calculate the [Levenshtein Distance](http://en.wikipedia.org/wiki/Levenshtein_distance)

The library is fully capable of working with non-ascii strings. But the strings are not normalized. That is left as a user-dependant use case. Please normalize the strings before passing it to the library if you have such a requirement.
- https://blog.golang.org/normalization

Strings of 65535 runes or fewer keep the uint16 row. Longer strings use an int row, so the distance does not wrap.

Install
-------

    go get github.com/agnivade/levenshtein

Example
-------

```go
package main

import (
	"fmt"
	"github.com/agnivade/levenshtein"
)

func main() {
	s1 := "kitten"
	s2 := "sitting"
	distance := levenshtein.ComputeDistance(s1, s2)
	fmt.Printf("The distance between %s and %s is %d.\n", s1, s2, distance)
	// Output:
	// The distance between kitten and sitting is 3.
}

```

Benchmarks
----------

```
goos: darwin
goarch: arm64
pkg: github.com/agnivade/levenshtein
cpu: Apple M4
                      │  bench.out  │
                      │   sec/op    │
Simple/ASCII-10         123.8n ± 0%
Simple/French-10        212.6n ± 1%
Simple/Nordic-10        365.9n ± 0%
Simple/Long_lead-10     224.5n ± 0%
Simple/Long_middle-10   379.9n ± 0%
Simple/Long_trail-10    580.8n ± 0%
Simple/Long_diff-10     8.008µ ± 0%
Simple/Tibetan-10       459.5n ± 0%
geomean                 452.4n

                      │  bench.out   │
                      │     B/op     │
Simple/ASCII-10         0.000 ± 0%
Simple/French-10        0.000 ± 0%
Simple/Nordic-10        0.000 ± 0%
Simple/Long_lead-10     368.0 ± 0%
Simple/Long_middle-10   544.0 ± 0%
Simple/Long_trail-10    576.0 ± 0%
Simple/Long_diff-10     720.0 ± 0%
Simple/Tibetan-10       0.000 ± 0%
geomean                            ¹
¹ summaries must be >0 to compute geomean

                      │  bench.out   │
                      │  allocs/op   │
Simple/ASCII-10         0.000 ± 0%
Simple/French-10        0.000 ± 0%
Simple/Nordic-10        0.000 ± 0%
Simple/Long_lead-10     2.000 ± 0%
Simple/Long_middle-10   2.000 ± 0%
Simple/Long_trail-10    2.000 ± 0%
Simple/Long_diff-10     3.000 ± 0%
Simple/Tibetan-10       0.000 ± 0%
geomean                            ¹
¹ summaries must be >0 to compute geomean
```

Comparisons with other libraries
--------------------------------

### github.com/dgryski/trifles

```
goos: darwin
goarch: arm64
pkg: github.com/agnivade/levenshtein
cpu: Apple M4
                    │   dgryski   │               agniva                │
                    │   sec/op    │   sec/op     vs base                │
All/case=ASCII-10     288.4n ± 0%   123.9n ± 1%  -57.05% (p=0.000 n=20)
All/case=French-10    518.8n ± 0%   211.7n ± 1%  -59.20% (p=0.000 n=20)
All/case=Nordic-10    963.8n ± 0%   369.4n ± 1%  -61.67% (p=0.000 n=20)
All/case=Tibetan-10   795.6n ± 0%   460.1n ± 0%  -42.18% (p=0.000 n=20)
geomean               582.0n        258.4n       -55.60%

                    │  dgryski   │                 agniva                 │
                    │    B/op    │   B/op     vs base                     │
All/case=ASCII-10     96.00 ± 0%   0.00 ± 0%  -100.00% (p=0.000 n=20)
All/case=French-10    128.0 ± 0%    0.0 ± 0%  -100.00% (p=0.000 n=20)
All/case=Nordic-10    192.0 ± 0%    0.0 ± 0%  -100.00% (p=0.000 n=20)
All/case=Tibetan-10   160.0 ± 0%    0.0 ± 0%  -100.00% (p=0.000 n=20)
geomean               139.4                   ?                       ¹ ²
¹ summaries must be >0 to compute geomean
² ratios must be >0 to compute geomean

                    │  dgryski   │                 agniva                  │
                    │ allocs/op  │ allocs/op   vs base                     │
All/case=ASCII-10     1.000 ± 0%   0.000 ± 0%  -100.00% (p=0.000 n=20)
All/case=French-10    1.000 ± 0%   0.000 ± 0%  -100.00% (p=0.000 n=20)
All/case=Nordic-10    1.000 ± 0%   0.000 ± 0%  -100.00% (p=0.000 n=20)
All/case=Tibetan-10   1.000 ± 0%   0.000 ± 0%  -100.00% (p=0.000 n=20)
geomean               1.000                    ?                       ¹ ²
¹ summaries must be >0 to compute geomean
² ratios must be >0 to compute geomean
```

### github.com/arbovm/levenshtein

```
goos: darwin
goarch: arm64
pkg: github.com/agnivade/levenshtein
cpu: Apple M4
                    │   arbovm    │               agniva                │
                    │   sec/op    │   sec/op     vs base                │
All/case=ASCII-10     283.1n ± 1%   123.9n ± 1%  -56.23% (p=0.000 n=20)
All/case=French-10    516.4n ± 0%   211.7n ± 1%  -59.01% (p=0.000 n=20)
All/case=Nordic-10    978.9n ± 0%   369.4n ± 1%  -62.26% (p=0.000 n=20)
All/case=Tibetan-10   804.9n ± 0%   460.1n ± 0%  -42.84% (p=0.000 n=20)
geomean               582.6n        258.4n       -55.65%

                    │   arbovm   │                 agniva                 │
                    │    B/op    │   B/op     vs base                     │
All/case=ASCII-10     96.00 ± 0%   0.00 ± 0%  -100.00% (p=0.000 n=20)
All/case=French-10    128.0 ± 0%    0.0 ± 0%  -100.00% (p=0.000 n=20)
All/case=Nordic-10    192.0 ± 0%    0.0 ± 0%  -100.00% (p=0.000 n=20)
All/case=Tibetan-10   160.0 ± 0%    0.0 ± 0%  -100.00% (p=0.000 n=20)
geomean               139.4                   ?                       ¹ ²
¹ summaries must be >0 to compute geomean
² ratios must be >0 to compute geomean

                    │   arbovm   │                 agniva                  │
                    │ allocs/op  │ allocs/op   vs base                     │
All/case=ASCII-10     1.000 ± 0%   0.000 ± 0%  -100.00% (p=0.000 n=20)
All/case=French-10    1.000 ± 0%   0.000 ± 0%  -100.00% (p=0.000 n=20)
All/case=Nordic-10    1.000 ± 0%   0.000 ± 0%  -100.00% (p=0.000 n=20)
All/case=Tibetan-10   1.000 ± 0%   0.000 ± 0%  -100.00% (p=0.000 n=20)
geomean               1.000                    ?                       ¹ ²
¹ summaries must be >0 to compute geomean
² ratios must be >0 to compute geomean
```