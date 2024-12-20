package arg

import "fmt"

// Subcommand returns the user struct for the subcommand selected by
// the command line arguments most recently processed by the parser.
// The return value is always a pointer to a struct. If no subcommand
// was specified then it returns the top-level arguments struct. If
// no command line arguments have been processed by this parser then it
// returns nil.
func (p *Parser) Subcommand() interface{} {
	if len(p.subcommand) == 0 {
		return nil
	}
	cmd, err := p.lookupCommand(p.subcommand...)
	if err != nil {
		return nil
	}
	return p.val(cmd.dest).Interface()
}

// SubcommandNames returns the sequence of subcommands specified by the
// user. If no subcommands were given then it returns an empty slice.
func (p *Parser) SubcommandNames() []string {
	return p.subcommand
}

// lookupCommand finds a subcommand based on a sequence of subcommand names. The
// first string should be a top-level subcommand, the next should be a child
// subcommand of that subcommand, and so on. If no strings are given then the
// root command is returned. If no such subcommand exists then an error is
// returned.
func (p *Parser) lookupCommand(path ...string) (*command, error) {
	cmd := p.cmd
	for _, name := range path {
		found := findSubcommand(cmd.subcommands, name)
		if found == nil {
			return nil, fmt.Errorf("%q is not a subcommand of %s", name, cmd.name)
		}
		cmd = found
	}
	return cmd, nil
}
