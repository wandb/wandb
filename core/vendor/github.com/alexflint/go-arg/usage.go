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
	p.failWithCommand(msg, p.cmd)
}

// failWithCommand prints usage information for the given subcommand to stderr and exits with non-zero status
func (p *Parser) failWithCommand(msg string, cmd *command) {
	p.writeUsageForCommand(stderr, cmd)
	fmt.Fprintln(stderr, "error:", msg)
	osExit(-1)
}

// WriteUsage writes usage information to the given writer
func (p *Parser) WriteUsage(w io.Writer) {
	cmd := p.cmd
	if p.lastCmd != nil {
		cmd = p.lastCmd
	}
	p.writeUsageForCommand(w, cmd)
}

// writeUsageForCommand writes usage information for the given subcommand
func (p *Parser) writeUsageForCommand(w io.Writer, cmd *command) {
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

	// write the positional component of the usage message
	for _, spec := range positionals {
		// prefix with a space
		fmt.Fprint(w, " ")
		if spec.cardinality == multiple {
			if !spec.required {
				fmt.Fprint(w, "[")
			}
			fmt.Fprintf(w, "%s [%s ...]", spec.placeholder, spec.placeholder)
			if !spec.required {
				fmt.Fprint(w, "]")
			}
		} else {
			fmt.Fprint(w, spec.placeholder)
		}
	}

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
	p.writeHelpForCommand(w, cmd)
}

// writeHelp writes the usage string for the given subcommand
func (p *Parser) writeHelpForCommand(w io.Writer, cmd *command) {
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
	p.writeUsageForCommand(w, cmd)

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

func synopsis(spec *spec, form string) string {
	if spec.cardinality == zero {
		return form
	}
	return form + " " + spec.placeholder
}
