package arg

var registrations []interface{}

// Register adds a struct that will be added to the command line arguments parsed
// by any call to arg.Parse or arg.MustParse
//
// This allows you to have command line arguments defined per-package
//
//	package foo
//
//	var args struct {
//		CacheSize int `arg:"--foo-cache-size"`
//	}
//
//	func init() {
//		arg.Register(&args)
//	}
func Register(dest any) {
	registrations = append(registrations, dest)
}
