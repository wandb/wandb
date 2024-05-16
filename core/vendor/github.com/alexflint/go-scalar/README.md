[![GoDoc](https://godoc.org/github.com/alexflint/go-scalar?status.svg)](https://godoc.org/github.com/alexflint/go-scalar)
[![Build Status](https://travis-ci.org/alexflint/go-scalar.svg?branch=master)](https://travis-ci.org/alexflint/go-scalar)
[![Coverage Status](https://coveralls.io/repos/alexflint/go-scalar/badge.svg?branch=master&service=github)](https://coveralls.io/github/alexflint/go-scalar?branch=master)
[![Report Card](https://goreportcard.com/badge/github.com/alexflint/go-scalar)](https://goreportcard.com/badge/github.com/alexflint/go-scalar)

## Scalar parsing library

Scalar is a library for parsing strings into arbitrary scalars (integers,
floats, strings, booleans, etc). It is helpful for tasks such as parsing
strings passed as environment variables or command line arguments.

```shell
go get github.com/alexflint/go-scalar
```

The main API works as follows:

```go
var value int
err := scalar.Parse(&value, "123")
```

There is also a variant that takes a `reflect.Value`:

```go
var value int
err := scalar.ParseValue(reflect.ValueOf(&value), "123")
```
