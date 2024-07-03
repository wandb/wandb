package arg

import (
	"encoding"
	"encoding/csv"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strings"

	scalar "github.com/alexflint/go-scalar"
)

// path represents a sequence of steps to find the output location for an
// argument or subcommand in the final destination struct
type path struct {
	root   int                   // index of the destination struct
	fields []reflect.StructField // sequence of struct fields to traverse
}

// String gets a string representation of the given path
func (p path) String() string {
	s := "args"
	for _, f := range p.fields {
		s += "." + f.Name
	}
	return s
}

// Child gets a new path representing a child of this path.
func (p path) Child(f reflect.StructField) path {
	// copy the entire slice of fields to avoid possible slice overwrite
	subfields := make([]reflect.StructField, len(p.fields)+1)
	copy(subfields, p.fields)
	subfields[len(subfields)-1] = f
	return path{
		root:   p.root,
		fields: subfields,
	}
}

// spec represents a command line option
type spec struct {
	dest          path
	field         reflect.StructField // the struct field from which this option was created
	long          string              // the --long form for this option, or empty if none
	short         string              // the -s short form for this option, or empty if none
	cardinality   cardinality         // determines how many tokens will be present (possible values: zero, one, multiple)
	required      bool                // if true, this option must be present on the command line
	positional    bool                // if true, this option will be looked for in the positional flags
	separate      bool                // if true, each slice and map entry will have its own --flag
	help          string              // the help text for this option
	env           string              // the name of the environment variable for this option, or empty for none
	defaultValue  reflect.Value       // default value for this option
	defaultString string              // default value for this option, in string form to be displayed in help text
	placeholder   string              // placeholder string in help
}

// command represents a named subcommand, or the top-level command
type command struct {
	name        string
	aliases     []string
	help        string
	dest        path
	specs       []*spec
	subcommands []*command
	parent      *command
}

// ErrHelp indicates that the builtin -h or --help were provided
var ErrHelp = errors.New("help requested by user")

// ErrVersion indicates that the builtin --version was provided
var ErrVersion = errors.New("version requested by user")

// for monkey patching in example code
var mustParseExit = os.Exit

// MustParse processes command line arguments and exits upon failure
func MustParse(dest ...interface{}) *Parser {
	return mustParse(Config{Exit: mustParseExit}, dest...)
}

// mustParse is a helper that facilitates testing
func mustParse(config Config, dest ...interface{}) *Parser {
	p, err := NewParser(config, dest...)
	if err != nil {
		fmt.Fprintln(config.Out, err)
		config.Exit(-1)
		return nil
	}

	p.MustParse(flags())
	return p
}

// Parse processes command line arguments and stores them in dest
func Parse(dest ...interface{}) error {
	p, err := NewParser(Config{}, dest...)
	if err != nil {
		return err
	}
	return p.Parse(flags())
}

// flags gets all command line arguments other than the first (program name)
func flags() []string {
	if len(os.Args) == 0 { // os.Args could be empty
		return nil
	}
	return os.Args[1:]
}

// Config represents configuration options for an argument parser
type Config struct {
	// Program is the name of the program used in the help text
	Program string

	// IgnoreEnv instructs the library not to read environment variables
	IgnoreEnv bool

	// IgnoreDefault instructs the library not to reset the variables to the
	// default values, including pointers to sub commands
	IgnoreDefault bool

	// StrictSubcommands intructs the library not to allow global commands after
	// subcommand
	StrictSubcommands bool

	// Exit is called to terminate the process with an error code (defaults to os.Exit)
	Exit func(int)

	// Out is where help text, usage text, and failure messages are printed (defaults to os.Stdout)
	Out io.Writer
}

// Parser represents a set of command line options with destination values
type Parser struct {
	cmd         *command
	roots       []reflect.Value
	config      Config
	version     string
	description string
	epilogue    string

	// the following field changes during processing of command line arguments
	subcommand []string
}

// Versioned is the interface that the destination struct should implement to
// make a version string appear at the top of the help message.
type Versioned interface {
	// Version returns the version string that will be printed on a line by itself
	// at the top of the help message.
	Version() string
}

// Described is the interface that the destination struct should implement to
// make a description string appear at the top of the help message.
type Described interface {
	// Description returns the string that will be printed on a line by itself
	// at the top of the help message.
	Description() string
}

// Epilogued is the interface that the destination struct should implement to
// add an epilogue string at the bottom of the help message.
type Epilogued interface {
	// Epilogue returns the string that will be printed on a line by itself
	// at the end of the help message.
	Epilogue() string
}

// walkFields calls a function for each field of a struct, recursively expanding struct fields.
func walkFields(t reflect.Type, visit func(field reflect.StructField, owner reflect.Type) bool) {
	walkFieldsImpl(t, visit, nil)
}

func walkFieldsImpl(t reflect.Type, visit func(field reflect.StructField, owner reflect.Type) bool, path []int) {
	for i := 0; i < t.NumField(); i++ {
		field := t.Field(i)
		field.Index = make([]int, len(path)+1)
		copy(field.Index, append(path, i))
		expand := visit(field, t)
		if expand && field.Type.Kind() == reflect.Struct {
			var subpath []int
			if field.Anonymous {
				subpath = append(path, i)
			}
			walkFieldsImpl(field.Type, visit, subpath)
		}
	}
}

// NewParser constructs a parser from a list of destination structs
func NewParser(config Config, dests ...interface{}) (*Parser, error) {
	// fill in defaults
	if config.Exit == nil {
		config.Exit = os.Exit
	}
	if config.Out == nil {
		config.Out = os.Stdout
	}

	// first pick a name for the command for use in the usage text
	var name string
	switch {
	case config.Program != "":
		name = config.Program
	case len(os.Args) > 0:
		name = filepath.Base(os.Args[0])
	default:
		name = "program"
	}

	// construct a parser
	p := Parser{
		cmd:    &command{name: name},
		config: config,
	}

	// make a list of roots
	for _, dest := range dests {
		p.roots = append(p.roots, reflect.ValueOf(dest))
	}

	// process each of the destination values
	for i, dest := range dests {
		t := reflect.TypeOf(dest)
		if t.Kind() != reflect.Ptr {
			panic(fmt.Sprintf("%s is not a pointer (did you forget an ampersand?)", t))
		}

		cmd, err := cmdFromStruct(name, path{root: i}, t)
		if err != nil {
			return nil, err
		}

		// for backwards compatibility, add nonzero field values as defaults
		// this applies only to the top-level command, not to subcommands (this inconsistency
		// is the reason that this method for setting default values was deprecated)
		for _, spec := range cmd.specs {
			// get the value
			v := p.val(spec.dest)

			// if the value is the "zero value" (e.g. nil pointer, empty struct) then ignore
			if isZero(v) {
				continue
			}

			// store as a default
			spec.defaultValue = v

			// we need a string to display in help text
			// if MarshalText is implemented then use that
			if m, ok := v.Interface().(encoding.TextMarshaler); ok {
				s, err := m.MarshalText()
				if err != nil {
					return nil, fmt.Errorf("%v: error marshaling default value to string: %v", spec.dest, err)
				}
				spec.defaultString = string(s)
			} else {
				spec.defaultString = fmt.Sprintf("%v", v)
			}
		}

		p.cmd.specs = append(p.cmd.specs, cmd.specs...)
		p.cmd.subcommands = append(p.cmd.subcommands, cmd.subcommands...)

		if dest, ok := dest.(Versioned); ok {
			p.version = dest.Version()
		}
		if dest, ok := dest.(Described); ok {
			p.description = dest.Description()
		}
		if dest, ok := dest.(Epilogued); ok {
			p.epilogue = dest.Epilogue()
		}
	}

	return &p, nil
}

func cmdFromStruct(name string, dest path, t reflect.Type) (*command, error) {
	// commands can only be created from pointers to structs
	if t.Kind() != reflect.Ptr {
		return nil, fmt.Errorf("subcommands must be pointers to structs but %s is a %s",
			dest, t.Kind())
	}

	t = t.Elem()
	if t.Kind() != reflect.Struct {
		return nil, fmt.Errorf("subcommands must be pointers to structs but %s is a pointer to %s",
			dest, t.Kind())
	}

	cmd := command{
		name: name,
		dest: dest,
	}

	var errs []string
	walkFields(t, func(field reflect.StructField, t reflect.Type) bool {
		// check for the ignore switch in the tag
		tag := field.Tag.Get("arg")
		if tag == "-" {
			return false
		}

		// if this is an embedded struct then recurse into its fields, even if
		// it is unexported, because exported fields on unexported embedded
		// structs are still writable
		if field.Anonymous && field.Type.Kind() == reflect.Struct {
			return true
		}

		// ignore any other unexported field
		if !isExported(field.Name) {
			return false
		}

		// duplicate the entire path to avoid slice overwrites
		subdest := dest.Child(field)
		spec := spec{
			dest:  subdest,
			field: field,
			long:  strings.ToLower(field.Name),
		}

		help, exists := field.Tag.Lookup("help")
		if exists {
			spec.help = help
		}

		// process each comma-separated part of the tag
		var isSubcommand bool
		for _, key := range strings.Split(tag, ",") {
			if key == "" {
				continue
			}
			key = strings.TrimLeft(key, " ")
			var value string
			if pos := strings.Index(key, ":"); pos != -1 {
				value = key[pos+1:]
				key = key[:pos]
			}

			switch {
			case strings.HasPrefix(key, "---"):
				errs = append(errs, fmt.Sprintf("%s.%s: too many hyphens", t.Name(), field.Name))
			case strings.HasPrefix(key, "--"):
				spec.long = key[2:]
			case strings.HasPrefix(key, "-"):
				if len(key) > 2 {
					errs = append(errs, fmt.Sprintf("%s.%s: short arguments must be one character only",
						t.Name(), field.Name))
					return false
				}
				spec.short = key[1:]
			case key == "required":
				spec.required = true
			case key == "positional":
				spec.positional = true
			case key == "separate":
				spec.separate = true
			case key == "help": // deprecated
				spec.help = value
			case key == "env":
				// Use override name if provided
				if value != "" {
					spec.env = value
				} else {
					spec.env = strings.ToUpper(field.Name)
				}
			case key == "subcommand":
				// decide on a name for the subcommand
				var cmdnames []string
				if value == "" {
					cmdnames = []string{strings.ToLower(field.Name)}
				} else {
					cmdnames = strings.Split(value, "|")
				}
				for i := range cmdnames {
					cmdnames[i] = strings.TrimSpace(cmdnames[i])
				}

				// parse the subcommand recursively
				subcmd, err := cmdFromStruct(cmdnames[0], subdest, field.Type)
				if err != nil {
					errs = append(errs, err.Error())
					return false
				}

				subcmd.aliases = cmdnames[1:]
				subcmd.parent = &cmd
				subcmd.help = field.Tag.Get("help")

				cmd.subcommands = append(cmd.subcommands, subcmd)
				isSubcommand = true
			default:
				errs = append(errs, fmt.Sprintf("unrecognized tag '%s' on field %s", key, tag))
				return false
			}
		}

		// placeholder is the string used in the help text like this: "--somearg PLACEHOLDER"
		placeholder, hasPlaceholder := field.Tag.Lookup("placeholder")
		if hasPlaceholder {
			spec.placeholder = placeholder
		} else if spec.long != "" {
			spec.placeholder = strings.ToUpper(spec.long)
		} else {
			spec.placeholder = strings.ToUpper(spec.field.Name)
		}

		// if this is a subcommand then we've done everything we need to do
		if isSubcommand {
			return false
		}

		// check whether this field is supported. It's good to do this here rather than
		// wait until ParseValue because it means that a program with invalid argument
		// fields will always fail regardless of whether the arguments it received
		// exercised those fields.
		var err error
		spec.cardinality, err = cardinalityOf(field.Type)
		if err != nil {
			errs = append(errs, fmt.Sprintf("%s.%s: %s fields are not supported",
				t.Name(), field.Name, field.Type.String()))
			return false
		}

		defaultString, hasDefault := field.Tag.Lookup("default")
		if hasDefault {
			// we do not support default values for maps and slices
			if spec.cardinality == multiple {
				errs = append(errs, fmt.Sprintf("%s.%s: default values are not supported for slice or map fields",
					t.Name(), field.Name))
				return false
			}

			// a required field cannot also have a default value
			if spec.required {
				errs = append(errs, fmt.Sprintf("%s.%s: 'required' cannot be used when a default value is specified",
					t.Name(), field.Name))
				return false
			}

			// parse the default value
			spec.defaultString = defaultString
			if field.Type.Kind() == reflect.Ptr {
				// here we have a field of type *T and we create a new T, no need to dereference
				// in order for the value to be settable
				spec.defaultValue = reflect.New(field.Type.Elem())
			} else {
				// here we have a field of type T and we create a new T and then dereference it
				// so that the resulting value is settable
				spec.defaultValue = reflect.New(field.Type).Elem()
			}
			err := scalar.ParseValue(spec.defaultValue, defaultString)
			if err != nil {
				errs = append(errs, fmt.Sprintf("%s.%s: error processing default value: %v", t.Name(), field.Name, err))
				return false
			}
		}

		// add the spec to the list of specs
		cmd.specs = append(cmd.specs, &spec)

		// if this was an embedded field then we already returned true up above
		return false
	})

	if len(errs) > 0 {
		return nil, errors.New(strings.Join(errs, "\n"))
	}

	// check that we don't have both positionals and subcommands
	var hasPositional bool
	for _, spec := range cmd.specs {
		if spec.positional {
			hasPositional = true
		}
	}
	if hasPositional && len(cmd.subcommands) > 0 {
		return nil, fmt.Errorf("%s cannot have both subcommands and positional arguments", dest)
	}

	return &cmd, nil
}

// Parse processes the given command line option, storing the results in the field
// of the structs from which NewParser was constructed
func (p *Parser) Parse(args []string) error {
	err := p.process(args)
	if err != nil {
		// If -h or --help were specified then make sure help text supercedes other errors
		for _, arg := range args {
			if arg == "-h" || arg == "--help" {
				return ErrHelp
			}
			if arg == "--" {
				break
			}
		}
	}
	return err
}

func (p *Parser) MustParse(args []string) {
	err := p.Parse(args)
	switch {
	case err == ErrHelp:
		p.WriteHelpForSubcommand(p.config.Out, p.subcommand...)
		p.config.Exit(0)
	case err == ErrVersion:
		fmt.Fprintln(p.config.Out, p.version)
		p.config.Exit(0)
	case err != nil:
		p.FailSubcommand(err.Error(), p.subcommand...)
	}
}

// process environment vars for the given arguments
func (p *Parser) captureEnvVars(specs []*spec, wasPresent map[*spec]bool) error {
	for _, spec := range specs {
		if spec.env == "" {
			continue
		}

		value, found := os.LookupEnv(spec.env)
		if !found {
			continue
		}

		if spec.cardinality == multiple {
			// expect a CSV string in an environment
			// variable in the case of multiple values
			var values []string
			var err error
			if len(strings.TrimSpace(value)) > 0 {
				values, err = csv.NewReader(strings.NewReader(value)).Read()
				if err != nil {
					return fmt.Errorf(
						"error reading a CSV string from environment variable %s with multiple values: %v",
						spec.env,
						err,
					)
				}
			}
			if err = setSliceOrMap(p.val(spec.dest), values, !spec.separate); err != nil {
				return fmt.Errorf(
					"error processing environment variable %s with multiple values: %v",
					spec.env,
					err,
				)
			}
		} else {
			if err := scalar.ParseValue(p.val(spec.dest), value); err != nil {
				return fmt.Errorf("error processing environment variable %s: %v", spec.env, err)
			}
		}
		wasPresent[spec] = true
	}

	return nil
}

// process goes through arguments one-by-one, parses them, and assigns the result to
// the underlying struct field
func (p *Parser) process(args []string) error {
	// track the options we have seen
	wasPresent := make(map[*spec]bool)

	// union of specs for the chain of subcommands encountered so far
	curCmd := p.cmd
	p.subcommand = nil

	// make a copy of the specs because we will add to this list each time we expand a subcommand
	specs := make([]*spec, len(curCmd.specs))
	copy(specs, curCmd.specs)

	// deal with environment vars
	if !p.config.IgnoreEnv {
		err := p.captureEnvVars(specs, wasPresent)
		if err != nil {
			return err
		}
	}

	// determine if the current command has a version option spec
	var hasVersionOption bool
	for _, spec := range curCmd.specs {
		if spec.long == "version" {
			hasVersionOption = true
			break
		}
	}

	// process each string from the command line
	var allpositional bool
	var positionals []string

	// must use explicit for loop, not range, because we manipulate i inside the loop
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if arg == "--" {
			allpositional = true
			continue
		}

		if !isFlag(arg) || allpositional {
			// each subcommand can have either subcommands or positionals, but not both
			if len(curCmd.subcommands) == 0 {
				positionals = append(positionals, arg)
				continue
			}

			// if we have a subcommand then make sure it is valid for the current context
			subcmd := findSubcommand(curCmd.subcommands, arg)
			if subcmd == nil {
				return fmt.Errorf("invalid subcommand: %s", arg)
			}

			// instantiate the field to point to a new struct
			v := p.val(subcmd.dest)
			if v.IsNil() {
				v.Set(reflect.New(v.Type().Elem())) // we already checked that all subcommands are struct pointers
			}

			// add the new options to the set of allowed options
			if p.config.StrictSubcommands {
				specs = make([]*spec, len(subcmd.specs))
				copy(specs, subcmd.specs)
			} else {
				specs = append(specs, subcmd.specs...)
			}

			// capture environment vars for these new options
			if !p.config.IgnoreEnv {
				err := p.captureEnvVars(subcmd.specs, wasPresent)
				if err != nil {
					return err
				}
			}

			curCmd = subcmd
			p.subcommand = append(p.subcommand, arg)
			continue
		}

		// check for special --help and --version flags
		switch arg {
		case "-h", "--help":
			return ErrHelp
		case "--version":
			if !hasVersionOption && p.version != "" {
				return ErrVersion
			}
		}

		// check for an equals sign, as in "--foo=bar"
		var value string
		opt := strings.TrimLeft(arg, "-")
		if pos := strings.Index(opt, "="); pos != -1 {
			value = opt[pos+1:]
			opt = opt[:pos]
		}

		// lookup the spec for this option (note that the "specs" slice changes as
		// we expand subcommands so it is better not to use a map)
		spec := findOption(specs, opt)
		if spec == nil || opt == "" {
			return fmt.Errorf("unknown argument %s", arg)
		}
		wasPresent[spec] = true

		// deal with the case of multiple values
		if spec.cardinality == multiple {
			var values []string
			if value == "" {
				for i+1 < len(args) && !isFlag(args[i+1]) && args[i+1] != "--" {
					values = append(values, args[i+1])
					i++
					if spec.separate {
						break
					}
				}
			} else {
				values = append(values, value)
			}
			err := setSliceOrMap(p.val(spec.dest), values, !spec.separate)
			if err != nil {
				return fmt.Errorf("error processing %s: %v", arg, err)
			}
			continue
		}

		// if it's a flag and it has no value then set the value to true
		// use boolean because this takes account of TextUnmarshaler
		if spec.cardinality == zero && value == "" {
			value = "true"
		}

		// if we have something like "--foo" then the value is the next argument
		if value == "" {
			if i+1 == len(args) {
				return fmt.Errorf("missing value for %s", arg)
			}
			if !nextIsNumeric(spec.field.Type, args[i+1]) && isFlag(args[i+1]) {
				return fmt.Errorf("missing value for %s", arg)
			}
			value = args[i+1]
			i++
		}

		err := scalar.ParseValue(p.val(spec.dest), value)
		if err != nil {
			return fmt.Errorf("error processing %s: %v", arg, err)
		}
	}

	// process positionals
	for _, spec := range specs {
		if !spec.positional {
			continue
		}
		if len(positionals) == 0 {
			break
		}
		wasPresent[spec] = true
		if spec.cardinality == multiple {
			err := setSliceOrMap(p.val(spec.dest), positionals, true)
			if err != nil {
				return fmt.Errorf("error processing %s: %v", spec.field.Name, err)
			}
			positionals = nil
		} else {
			err := scalar.ParseValue(p.val(spec.dest), positionals[0])
			if err != nil {
				return fmt.Errorf("error processing %s: %v", spec.field.Name, err)
			}
			positionals = positionals[1:]
		}
	}
	if len(positionals) > 0 {
		return fmt.Errorf("too many positional arguments at '%s'", positionals[0])
	}

	// fill in defaults and check that all the required args were provided
	for _, spec := range specs {
		if wasPresent[spec] {
			continue
		}

		name := strings.ToLower(spec.field.Name)
		if spec.long != "" && !spec.positional {
			name = "--" + spec.long
		}

		if spec.required {
			if spec.short == "" && spec.long == "" {
				msg := fmt.Sprintf("environment variable %s is required", spec.env)
				return errors.New(msg)
			}

			msg := fmt.Sprintf("%s is required", name)
			if spec.env != "" {
				msg += " (or environment variable " + spec.env + ")"
			}

			return errors.New(msg)
		}

		if spec.defaultValue.IsValid() && !p.config.IgnoreDefault {
			// One issue here is that if the user now modifies the value then
			// the default value stored in the spec will be corrupted. There
			// is no general way to "deep-copy" values in Go, and we still
			// support the old-style method for specifying defaults as
			// Go values assigned directly to the struct field, so we are stuck.
			p.val(spec.dest).Set(spec.defaultValue)
		}
	}

	return nil
}

func nextIsNumeric(t reflect.Type, s string) bool {
	switch t.Kind() {
	case reflect.Ptr:
		return nextIsNumeric(t.Elem(), s)
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64, reflect.Float32, reflect.Float64, reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64, reflect.Uintptr:
		v := reflect.New(t)
		err := scalar.ParseValue(v, s)
		return err == nil
	default:
		return false
	}
}

// isFlag returns true if a token is a flag such as "-v" or "--user" but not "-" or "--"
func isFlag(s string) bool {
	return strings.HasPrefix(s, "-") && strings.TrimLeft(s, "-") != ""
}

// val returns a reflect.Value corresponding to the current value for the
// given path
func (p *Parser) val(dest path) reflect.Value {
	v := p.roots[dest.root]
	for _, field := range dest.fields {
		if v.Kind() == reflect.Ptr {
			if v.IsNil() {
				return reflect.Value{}
			}
			v = v.Elem()
		}

		v = v.FieldByIndex(field.Index)
	}
	return v
}

// findOption finds an option from its name, or returns null if no spec is found
func findOption(specs []*spec, name string) *spec {
	for _, spec := range specs {
		if spec.positional {
			continue
		}
		if spec.long == name || spec.short == name {
			return spec
		}
	}
	return nil
}

// findSubcommand finds a subcommand using its name, or returns null if no subcommand is found
func findSubcommand(cmds []*command, name string) *command {
	for _, cmd := range cmds {
		if cmd.name == name {
			return cmd
		}
		for _, alias := range cmd.aliases {
			if alias == name {
				return cmd
			}
		}
	}
	return nil
}
