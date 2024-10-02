package generate

// StringList provides yaml unmarshaler to accept both `string` and `[]string` as a valid type.
// Sourced from [gqlgen].
//
// [gqlgen]: https://github.com/99designs/gqlgen/blob/1a0b19feff6f02d2af6631c9d847bc243f8ede39/codegen/config/config.go#L302-L329
type StringList []string

func (a *StringList) UnmarshalYAML(unmarshal func(interface{}) error) error {
	var single string
	err := unmarshal(&single)
	if err == nil {
		*a = []string{single}
		return nil
	}

	var multi []string
	err = unmarshal(&multi)
	if err != nil {
		return err
	}

	*a = multi
	return nil
}
