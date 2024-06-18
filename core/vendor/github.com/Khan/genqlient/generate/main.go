// Package generate provides programmatic access to genqlient's functionality,
// and documentation of its configuration options.  For general usage
// documentation, see the project [GitHub].
//
// [GitHub]: https://github.com/Khan/genqlient
package generate

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/alexflint/go-arg"
)

// TODO(benkraft): Make this mockable for tests?
func warn(err error) {
	fmt.Println(err)
}

func readConfigGenerateAndWrite(configFilename string) error {
	var config *Config
	var err error
	if configFilename != "" {
		config, err = ReadAndValidateConfig(configFilename)
		if err != nil {
			return err
		}
	} else {
		config, err = ReadAndValidateConfigFromDefaultLocations()
		if err != nil {
			return err
		}
	}

	generated, err := Generate(config)
	if err != nil {
		return err
	}

	for filename, content := range generated {
		err = os.MkdirAll(filepath.Dir(filename), 0o755)
		if err != nil {
			return errorf(nil,
				"could not create parent directory for generated file %v: %v",
				filename, err)
		}

		err = os.WriteFile(filename, content, 0o644)
		if err != nil {
			return errorf(nil, "could not write generated file %v: %v",
				filename, err)
		}
	}
	return nil
}

type cliArgs struct {
	ConfigFilename string `arg:"positional" placeholder:"CONFIG" default:"" help:"path to genqlient configuration (default: genqlient.yaml in current or any parent directory)"`
	Init           bool   `arg:"--init" help:"write out and use a default config file"`
}

func (cliArgs) Description() string {
	return strings.TrimSpace(`
Generates GraphQL client code for a given schema and queries.
See https://github.com/Khan/genqlient for full documentation.
`)
}

// Main is the command-line entrypoint to genqlient; it's equivalent to calling
//
//	go run github.com/Khan/genqlient
//
// For lower-level control over genqlient's operation, see [Generate].
func Main() {
	exitIfError := func(err error) {
		if err != nil {
			fmt.Println(err)
			os.Exit(1)
		}
	}

	var args cliArgs
	arg.MustParse(&args)
	if args.Init {
		filename := args.ConfigFilename
		if filename == "" {
			filename = "genqlient.yaml"
		}

		err := initConfig(filename)
		exitIfError(err)
	}
	err := readConfigGenerateAndWrite(args.ConfigFilename)
	exitIfError(err)
}
