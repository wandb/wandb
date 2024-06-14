package arg

import (
	"fmt"
	"io"
	"os"
	"strings"
)

// the width of the left column
const colWidth = 25

// to allow monkey patching in tests
var (
	stdout io.Writer = os.Stdout
	stderr io.Writer = os.Stderr
	osExit           = os.Exit
)

// Fail prints usage information to stderr and exits with non-zero status
func (p *Parser) Fail(msg string) {
	p.failWithSubcommand(msg, p.cmd)
}

// FailSubcommand prints usage information for a specified subcommand to stderr,
// then exits with non-zero status. To write usage information for a top-level
// subcommand, provide just the name of that subcommand. To write usage
// information for a subcommand that is nested under another subcommand, provide
// a sequence of subcommand names starting with the top-level subcommand and so
// on down the tree.
func (p *Parser) FailSubcommand(msg string, subcommand ...string) error {
	cmd, err := p.lookupCommand(subcommand...)
	if err != nil {
		return err
	}
	p.failWithSubcommand(msg, cmd)
	return nil
}

// failWithSubcommand prints usage information for the given subcommand to stderr and exits with non-zero status
func (p *Parser) failWithSubcommand(msg string, cmd *command) {
	p.writeUsageForSubcommand(stderr, cmd)
	fmt.Fprintln(stderr, "error:", msg)
	osExit(-1)
}

// WriteUsage writes usage information to the given writer
func (p *Parser) WriteUsage(w io.Writer) {
	cmd := p.cmd
	if p.lastCmd != nil {
		cmd = p.lastCmd
	}
	p.writeUsageForSubcommand(w, cmd)
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
	p.writeUsageForSubcommand(w, cmd)
	return nil
}

// writeUsageForSubcommand writes usage information for the given subcommand
func (p *Parser) writeUsageForSubcommand(w io.Writer, cmd *command) {
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

	// make a list of ancestor commands so that we print with full context
	var ancestors []string
	ancestor := cmd
	for ancestor != nil {
		ancestors = append(ancestors, ancestor.name)
		ancestor = ancestor.parent
	}

	// print the beginning of the usage string
	fmt.Fprint(w, "Usage:")
	for i := len(ancestors) - 1; i >= 0; i-- {
		fmt.Fprint(w, " "+ancestors[i])
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
}

func printTwoCols(w io.Writer, left, help string, defaultVal string, envVal string) {
	lhs := "  " + left
	fmt.Fprint(w, lhs)
	if help != "" {
		if len(lhs)+2 < colWidth {
			fmt.Fprint(w, strings.Repeat(" ", colWidth-len(lhs)))
		} else {
			fmt.Fprint(w, "\n"+strings.Repeat(" ", colWidth))
		}
		fmt.Fprint(w, help)
	}

	bracketsContent := []string{}

	if defaultVal != "" {
		bracketsContent = append(bracketsContent,
			fmt.Sprintf("default: %s", defaultVal),
		)
	}

	if envVal != "" {
		bracketsContent = append(bracketsContent,
			fmt.Sprintf("env: %s", envVal),
		)
	}

	if len(bracketsContent) > 0 {
		fmt.Fprintf(w, " [%s]", strings.Join(bracketsContent, ", "))
	}
	fmt.Fprint(w, "\n")
}

// WriteHelp writes the usage string followed by the full help string for each option
func (p *Parser) WriteHelp(w io.Writer) {
	cmd := p.cmd
	if p.lastCmd != nil {
		cmd = p.lastCmd
	}
	p.writeHelpForSubcommand(w, cmd)
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
	p.writeHelpForSubcommand(w, cmd)
	return nil
}

// writeHelp writes the usage string for the given subcommand
func (p *Parser) writeHelpForSubcommand(w io.Writer, cmd *command) {
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

	if p.description != "" {
		fmt.Fprintln(w, p.description)
	}
	p.writeUsageForSubcommand(w, cmd)

	// write the list of positionals
	if len(positionals) > 0 {
		fmt.Fprint(w, "\nPositional arguments:\n")
		for _, spec := range positionals {
			printTwoCols(w, spec.placeholder, spec.help, "", "")
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
		}
	}

	// write the list of built in options
	p.printOption(w, &spec{
		cardinality: zero,
		long:        "help",
		short:       "h",
		help:        "display this help and exit",
	})
	if p.version != "" {
		p.printOption(w, &spec{
			cardinality: zero,
			long:        "version",
			help:        "display version and exit",
		})
	}

	// write the list of subcommands
	if len(cmd.subcommands) > 0 {
		fmt.Fprint(w, "\nCommands:\n")
		for _, subcmd := range cmd.subcommands {
			printTwoCols(w, subcmd.name, subcmd.help, "", "")
		}
	}
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
		printTwoCols(w, strings.Join(ways, ", "), spec.help, spec.defaultVal, spec.env)
	}
}

// lookupCommand finds a subcommand based on a sequence of subcommand names. The
// first string should be a top-level subcommand, the next should be a child
// subcommand of that subcommand, and so on. If no strings are given then the
// root command is returned. If no such subcommand exists then an error is
// returned.
func (p *Parser) lookupCommand(path ...string) (*command, error) {
	cmd := p.cmd
	for _, name := range path {
		var found *command
		for _, child := range cmd.subcommands {
			if child.name == name {
				found = child
			}
		}
		if found == nil {
			return nil, fmt.Errorf("%q is not a subcommand of %s", name, cmd.name)
		}
		cmd = found
	}
	return cmd, nil
}

func synopsis(spec *spec, form string) string {
	if spec.cardinality == zero {
		return form
	}
	return form + " " + spec.placeholder
}
