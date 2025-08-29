package arg

import (
	"fmt"
	"io"
	"strings"
)

// the width of the left column
const colWidth = 25

// Fail prints usage information to stderr and exits with non-zero status
func (p *Parser) Fail(msg string) {
	p.FailSubcommand(msg)
}

// FailSubcommand prints usage information for a specified subcommand to stderr,
// then exits with non-zero status. To write usage information for a top-level
// subcommand, provide just the name of that subcommand. To write usage
// information for a subcommand that is nested under another subcommand, provide
// a sequence of subcommand names starting with the top-level subcommand and so
// on down the tree.
func (p *Parser) FailSubcommand(msg string, subcommand ...string) error {
	err := p.WriteUsageForSubcommand(p.config.Out, subcommand...)
	if err != nil {
		return err
	}

	fmt.Fprintln(p.config.Out, "error:", msg)
	p.config.Exit(-1)
	return nil
}

// WriteUsage writes usage information to the given writer
func (p *Parser) WriteUsage(w io.Writer) {
	p.WriteUsageForSubcommand(w, p.subcommand...)
}

// WriteUsageForSubcommand writes the usage information for a specified
// subcommand. To write usage information for a top-level subcommand, provide
// just the name of that subcommand. To write usage information for a subcommand
// that is nested under another subcommand, provide a sequence of subcommand
// names starting with the top-level subcommand and so on down the tree.
func (p *Parser) WriteUsageForSubcommand(w io.Writer, subcommand ...string) error {
	cmd, err := p.lookupCommand(subcommand...)
	if err != nil {
		return err
	}

	var positionals, longOptions, shortOptions []*spec
	for _, spec := range cmd.specs {
		switch {
		case spec.positional:
			positionals = append(positionals, spec)
		case spec.long != "":
			longOptions = append(longOptions, spec)
		case spec.short != "":
			shortOptions = append(shortOptions, spec)
		}
	}

	if p.version != "" {
		fmt.Fprintln(w, p.version)
	}

	// print the beginning of the usage string
	fmt.Fprintf(w, "Usage: %s", p.cmd.name)
	for _, s := range subcommand {
		fmt.Fprint(w, " "+s)
	}

	// write the option component of the usage message
	for _, spec := range shortOptions {
		// prefix with a space
		fmt.Fprint(w, " ")
		if !spec.required {
			fmt.Fprint(w, "[")
		}
		fmt.Fprint(w, synopsis(spec, "-"+spec.short))
		if !spec.required {
			fmt.Fprint(w, "]")
		}
	}

	for _, spec := range longOptions {
		// prefix with a space
		fmt.Fprint(w, " ")
		if !spec.required {
			fmt.Fprint(w, "[")
		}
		fmt.Fprint(w, synopsis(spec, "--"+spec.long))
		if !spec.required {
			fmt.Fprint(w, "]")
		}
	}

	// When we parse positionals, we check that:
	//  1. required positionals come before non-required positionals
	//  2. there is at most one multiple-value positional
	//  3. if there is a multiple-value positional then it comes after all other positionals
	// Here we merely print the usage string, so we do not explicitly re-enforce those rules

	// write the positionals in following form:
	//    REQUIRED1 REQUIRED2
	//    REQUIRED1 REQUIRED2 [OPTIONAL1 [OPTIONAL2]]
	//    REQUIRED1 REQUIRED2 REPEATED [REPEATED ...]
	//    REQUIRED1 REQUIRED2 [REPEATEDOPTIONAL [REPEATEDOPTIONAL ...]]
	//    REQUIRED1 REQUIRED2 [OPTIONAL1 [REPEATEDOPTIONAL [REPEATEDOPTIONAL ...]]]
	var closeBrackets int
	for _, spec := range positionals {
		fmt.Fprint(w, " ")
		if !spec.required {
			fmt.Fprint(w, "[")
			closeBrackets += 1
		}
		if spec.cardinality == multiple {
			fmt.Fprintf(w, "%s [%s ...]", spec.placeholder, spec.placeholder)
		} else {
			fmt.Fprint(w, spec.placeholder)
		}
	}
	fmt.Fprint(w, strings.Repeat("]", closeBrackets))

	// if the program supports subcommands, give a hint to the user about their existence
	if len(cmd.subcommands) > 0 {
		fmt.Fprint(w, " <command> [<args>]")
	}

	fmt.Fprint(w, "\n")
	return nil
}

// print prints a line like this:
//
//	--option FOO            A description of the option [default: 123]
//
// If the text on the left is longer than a certain threshold, the description is moved to the next line:
//
//	--verylongoptionoption VERY_LONG_VARIABLE
//	                        A description of the option [default: 123]
//
// If multiple "extras" are provided then they are put inside a single set of square brackets:
//
//	--option FOO            A description of the option [default: 123, env: FOO]
func print(w io.Writer, item, description string, bracketed ...string) {
	lhs := "  " + item
	fmt.Fprint(w, lhs)
	if description != "" {
		if len(lhs)+2 < colWidth {
			fmt.Fprint(w, strings.Repeat(" ", colWidth-len(lhs)))
		} else {
			fmt.Fprint(w, "\n"+strings.Repeat(" ", colWidth))
		}
		fmt.Fprint(w, description)
	}

	var brack string
	for _, s := range bracketed {
		if s != "" {
			if brack != "" {
				brack += ", "
			}
			brack += s
		}
	}

	if brack != "" {
		fmt.Fprintf(w, " [%s]", brack)
	}
	fmt.Fprint(w, "\n")
}

func withDefault(s string) string {
	if s == "" {
		return ""
	}
	return "default: " + s
}

func withEnv(env string) string {
	if env == "" {
		return ""
	}
	return "env: " + env
}

// WriteHelp writes the usage string followed by the full help string for each option
func (p *Parser) WriteHelp(w io.Writer) {
	p.WriteHelpForSubcommand(w, p.subcommand...)
}

// WriteHelpForSubcommand writes the usage string followed by the full help
// string for a specified subcommand. To write help for a top-level subcommand,
// provide just the name of that subcommand. To write help for a subcommand that
// is nested under another subcommand, provide a sequence of subcommand names
// starting with the top-level subcommand and so on down the tree.
func (p *Parser) WriteHelpForSubcommand(w io.Writer, subcommand ...string) error {
	cmd, err := p.lookupCommand(subcommand...)
	if err != nil {
		return err
	}

	var positionals, longOptions, shortOptions, envOnlyOptions []*spec
	var hasVersionOption bool
	for _, spec := range cmd.specs {
		switch {
		case spec.positional:
			positionals = append(positionals, spec)
		case spec.long != "":
			longOptions = append(longOptions, spec)
		case spec.short != "":
			shortOptions = append(shortOptions, spec)
		case spec.short == "" && spec.long == "":
			envOnlyOptions = append(envOnlyOptions, spec)
		}
	}

	if p.description != "" {
		fmt.Fprintln(w, p.description)
	}
	p.WriteUsageForSubcommand(w, subcommand...)

	// write the list of positionals
	if len(positionals) > 0 {
		fmt.Fprint(w, "\nPositional arguments:\n")
		for _, spec := range positionals {
			print(w, spec.placeholder, spec.help)
		}
	}

	// write the list of options with the short-only ones first to match the usage string
	if len(shortOptions)+len(longOptions) > 0 || cmd.parent == nil {
		fmt.Fprint(w, "\nOptions:\n")
		for _, spec := range shortOptions {
			p.printOption(w, spec)
		}
		for _, spec := range longOptions {
			p.printOption(w, spec)
			if spec.long == "version" {
				hasVersionOption = true
			}
		}
	}

	// obtain a flattened list of options from all ancestors
	var globals []*spec
	ancestor := cmd.parent
	for ancestor != nil {
		globals = append(globals, ancestor.specs...)
		ancestor = ancestor.parent
	}

	// write the list of global options
	if len(globals) > 0 {
		fmt.Fprint(w, "\nGlobal options:\n")
		for _, spec := range globals {
			p.printOption(w, spec)
			if spec.long == "version" {
				hasVersionOption = true
			}
		}
	}

	// write the list of built in options
	p.printOption(w, &spec{
		cardinality: zero,
		long:        "help",
		short:       "h",
		help:        "display this help and exit",
	})
	if !hasVersionOption && p.version != "" {
		p.printOption(w, &spec{
			cardinality: zero,
			long:        "version",
			help:        "display version and exit",
		})
	}

	// write the list of environment only variables
	if len(envOnlyOptions) > 0 {
		fmt.Fprint(w, "\nEnvironment variables:\n")
		for _, spec := range envOnlyOptions {
			p.printEnvOnlyVar(w, spec)
		}
	}

	// write the list of subcommands
	if len(cmd.subcommands) > 0 {
		fmt.Fprint(w, "\nCommands:\n")
		for _, subcmd := range cmd.subcommands {
			names := append([]string{subcmd.name}, subcmd.aliases...)
			print(w, strings.Join(names, ", "), subcmd.help)
		}
	}

	if p.epilogue != "" {
		fmt.Fprintln(w, "\n"+p.epilogue)
	}
	return nil
}

func (p *Parser) printOption(w io.Writer, spec *spec) {
	ways := make([]string, 0, 2)
	if spec.long != "" {
		ways = append(ways, synopsis(spec, "--"+spec.long))
	}
	if spec.short != "" {
		ways = append(ways, synopsis(spec, "-"+spec.short))
	}
	if len(ways) > 0 {
		print(w, strings.Join(ways, ", "), spec.help, withDefault(spec.defaultString), withEnv(spec.env))
	}
}

func (p *Parser) printEnvOnlyVar(w io.Writer, spec *spec) {
	ways := make([]string, 0, 2)
	if spec.required {
		ways = append(ways, "Required.")
	} else {
		ways = append(ways, "Optional.")
	}

	if spec.help != "" {
		ways = append(ways, spec.help)
	}

	print(w, spec.env, strings.Join(ways, " "), withDefault(spec.defaultString))
}

func synopsis(spec *spec, form string) string {
	// if the user omits the placeholder tag then we pick one automatically,
	// but if the user explicitly specifies an empty placeholder then we
	// leave out the placeholder in the help message
	if spec.cardinality == zero || spec.placeholder == "" {
		return form
	}
	return form + " " + spec.placeholder
}
