// sub-package for gowandb run options
package runopts

type RunParams struct {
}

type RunOption func(*RunParams)

func WithConfig() RunOption {
	return func(s *RunParams) {
	}
}

