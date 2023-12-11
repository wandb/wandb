package clienttest

//go:generate mockgen -destination clienttest_gen.go -package clienttest net/http RoundTripper
