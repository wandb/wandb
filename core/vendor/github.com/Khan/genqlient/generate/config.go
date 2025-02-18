package generate

import (
	_ "embed"
	"fmt"
	"go/token"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/tools/go/packages"
	"gopkg.in/yaml.v2"
)

var cfgFilenames = []string{".genqlient.yml", ".genqlient.yaml", "genqlient.yml", "genqlient.yaml"}

// Config represents genqlient's configuration, generally read from
// genqlient.yaml.
//
// Callers must call [Config.ValidateAndFillDefaults] before using the config.
type Config struct {
	// The following fields are documented in the [genqlient.yaml docs].
	//
	// [genqlient.yaml docs]: https://github.com/Khan/genqlient/blob/main/docs/genqlient.yaml
	Schema              StringList              `yaml:"schema"`
	Operations          StringList              `yaml:"operations"`
	Generated           string                  `yaml:"generated"`
	Package             string                  `yaml:"package"`
	ExportOperations    string                  `yaml:"export_operations"`
	ContextType         string                  `yaml:"context_type"`
	ClientGetter        string                  `yaml:"client_getter"`
	Bindings            map[string]*TypeBinding `yaml:"bindings"`
	PackageBindings     []*PackageBinding       `yaml:"package_bindings"`
	Casing              Casing                  `yaml:"casing"`
	Optional            string                  `yaml:"optional"`
	OptionalGenericType string                  `yaml:"optional_generic_type"`
	StructReferences    bool                    `yaml:"use_struct_references"`
	Extensions          bool                    `yaml:"use_extensions"`

	// Set to true to use features that aren't fully ready to use.
	//
	// This is primarily intended for genqlient's own tests.  These features
	// are likely BROKEN and come with NO EXPECTATION OF COMPATIBILITY.  Use
	// them at your own risk!
	AllowBrokenFeatures bool `yaml:"allow_broken_features"`

	// The directory of the config-file (relative to which all the other paths
	// are resolved).  Set by ValidateAndFillDefaults.
	baseDir string
	// The package-path into which we are generating.
	pkgPath string
}

// A TypeBinding represents a Go type to which genqlient will bind a particular
// GraphQL type, and is documented further in the [genqlient.yaml docs].
//
// [genqlient.yaml docs]: https://github.com/Khan/genqlient/blob/main/docs/genqlient.yaml
type TypeBinding struct {
	Type              string `yaml:"type"`
	ExpectExactFields string `yaml:"expect_exact_fields"`
	Marshaler         string `yaml:"marshaler"`
	Unmarshaler       string `yaml:"unmarshaler"`
}

// A PackageBinding represents a Go package for which genqlient will
// automatically generate [TypeBinding] values, and is documented further in
// the [genqlient.yaml docs].
//
// [genqlient.yaml docs]: https://github.com/Khan/genqlient/blob/main/docs/genqlient.yaml
type PackageBinding struct {
	Package string `yaml:"package"`
}

// CasingAlgorithm represents a way that genqlient can handle casing, and is
// documented further in the [genqlient.yaml docs].
//
// [genqlient.yaml docs]: https://github.com/Khan/genqlient/blob/main/docs/genqlient.yaml
type CasingAlgorithm string

const (
	CasingDefault CasingAlgorithm = "default"
	CasingRaw     CasingAlgorithm = "raw"
)

func (algo CasingAlgorithm) validate() error {
	switch algo {
	case CasingDefault, CasingRaw:
		return nil
	default:
		return errorf(nil, "unknown casing algorithm: %s", algo)
	}
}

// Casing wraps the casing-related options, and is documented further in
// the [genqlient.yaml docs].
//
// [genqlient.yaml docs]: https://github.com/Khan/genqlient/blob/main/docs/genqlient.yaml
type Casing struct {
	AllEnums CasingAlgorithm            `yaml:"all_enums"`
	Enums    map[string]CasingAlgorithm `yaml:"enums"`
}

func (casing *Casing) validate() error {
	if casing.AllEnums != "" {
		if err := casing.AllEnums.validate(); err != nil {
			return err
		}
	}
	for _, algo := range casing.Enums {
		if err := algo.validate(); err != nil {
			return err
		}
	}
	return nil
}

func (casing *Casing) forEnum(graphQLTypeName string) CasingAlgorithm {
	if specificConfig, ok := casing.Enums[graphQLTypeName]; ok {
		return specificConfig
	}
	if casing.AllEnums != "" {
		return casing.AllEnums
	}
	return CasingDefault
}

// pathJoin is like filepath.Join but 1) it only takes two argsuments,
// and b) if the second argument is an absolute path the first argument
// is ignored (similar to how python's os.path.join() works).
func pathJoin(a, b string) string {
	if filepath.IsAbs(b) {
		return b
	}
	return filepath.Join(a, b)
}

// Try to figure out the package-name and package-path of the given .go file.
//
// Returns a best-guess pkgName if possible, even on error.
func getPackageNameAndPath(filename string) (pkgName, pkgPath string, err error) {
	abs, err := filepath.Abs(filename)
	if err != nil { // path is totally bogus
		return "", "", err
	}

	dir := filepath.Dir(abs)
	// If we don't get a clean answer from go/packages, we'll use the
	// directory-name as a backup guess, as long as it's a valid identifier.
	pkgNameGuess := filepath.Base(dir)
	if !token.IsIdentifier(pkgNameGuess) {
		pkgNameGuess = ""
	}

	pkgs, err := packages.Load(&packages.Config{Mode: packages.NeedName}, dir)
	if err != nil { // e.g. not in a Go module
		return pkgNameGuess, "", err
	} else if len(pkgs) != 1 { // probably never happens?
		return pkgNameGuess, "", fmt.Errorf("found %v packages in %v, expected 1", len(pkgs), dir)
	}

	pkg := pkgs[0]
	// TODO(benkraft): Can PkgPath ever be empty while in a module? If so, we
	// could warn.
	if pkg.Name != "" { // found a good package!
		return pkg.Name, pkg.PkgPath, nil
	}

	// Package path is valid, but name is empty: probably an empty package
	// (within a valid module). If the package-path-suffix is a valid
	// identifier, that's a better guess than the directory-suffix, so use it.
	pathSuffix := filepath.Base(pkg.PkgPath)
	if token.IsIdentifier(pathSuffix) {
		pkgNameGuess = pathSuffix
	}

	if pkgNameGuess != "" {
		return pkgNameGuess, pkg.PkgPath, nil
	} else {
		return "", "", fmt.Errorf("no package found in %v", dir)
	}
}

// ValidateAndFillDefaults ensures that the configuration is valid, and fills
// in any options that were unspecified.
//
// The argument is the directory relative to which paths will be interpreted,
// typically the directory of the config file.
func (c *Config) ValidateAndFillDefaults(baseDir string) error {
	c.baseDir = baseDir
	for i := range c.Schema {
		c.Schema[i] = pathJoin(baseDir, c.Schema[i])
	}
	for i := range c.Operations {
		c.Operations[i] = pathJoin(baseDir, c.Operations[i])
	}
	if c.Generated == "" {
		c.Generated = "generated.go"
	}
	c.Generated = pathJoin(baseDir, c.Generated)
	if c.ExportOperations != "" {
		c.ExportOperations = pathJoin(baseDir, c.ExportOperations)
	}

	if c.ContextType == "" {
		c.ContextType = "context.Context"
	}

	if c.Optional != "" && c.Optional != "value" && c.Optional != "pointer" && c.Optional != "generic" {
		return errorf(nil, "optional must be one of: 'value' (default), 'pointer', or 'generic'")
	}

	if c.Optional == "generic" && c.OptionalGenericType == "" {
		return errorf(nil, "if optional is set to 'generic', optional_generic_type must be set to the fully"+
			"qualified name of a type with a single generic parameter"+
			"\nExample: \"github.com/Org/Repo/optional.Value\"")
	}

	if c.Package != "" && !token.IsIdentifier(c.Package) {
		// No need for link here -- if you're already setting the package
		// you know where to set the package.
		return errorf(nil, "invalid package in genqlient.yaml: '%v' is not a valid identifier", c.Package)
	}

	pkgName, pkgPath, err := getPackageNameAndPath(c.Generated)
	if err != nil {
		// Try to guess a name anyway (or use one you specified) -- pkgPath
		// isn't always needed. (But you'll run into trouble binding against
		// the generated package, so at least warn.)
		if c.Package != "" {
			warn(errorf(nil, "warning: unable to identify current package-path "+
				"(using 'package' config '%v'): %v\n", c.Package, err))
		} else if pkgName != "" {
			warn(errorf(nil, "warning: unable to identify current package-path "+
				"(using directory name '%v': %v\n", pkgName, err))
			c.Package = pkgName
		} else {
			return errorf(nil, "unable to guess package-name: %v"+
				"\nSet package name in genqlient.yaml"+
				"\nExample: https://github.com/Khan/genqlient/blob/main/example/genqlient.yaml#L6", err)
		}
	} else { // err == nil
		if c.Package == pkgName || c.Package == "" {
			c.Package = pkgName
		} else {
			warn(errorf(nil, "warning: package setting in genqlient.yaml '%v' looks wrong "+
				"('%v' is in package '%v') but proceeding with '%v' anyway\n",
				c.Package, c.Generated, pkgName, c.Package))
		}
	}
	// This is a no-op in some of the error cases, but it still doesn't hurt.
	c.pkgPath = pkgPath

	if len(c.PackageBindings) > 0 {
		for _, binding := range c.PackageBindings {
			if strings.HasSuffix(binding.Package, ".go") {
				// total heuristic -- but this is an easy mistake to make and
				// results in rather bizarre behavior from go/packages.
				return errorf(nil,
					"package %v looks like a file, but should be a package-name",
					binding.Package)
			}

			if binding.Package == c.pkgPath {
				warn(errorf(nil, "warning: package_bindings set to the same package as your generated "+
					"code ('%v'); this may cause nondeterministic output due to circularity", c.pkgPath))
			}

			mode := packages.NeedDeps | packages.NeedTypes
			pkgs, err := packages.Load(&packages.Config{
				Mode: mode,
			}, binding.Package)
			if err != nil {
				return err
			}

			if c.Bindings == nil {
				c.Bindings = map[string]*TypeBinding{}
			}

			for _, pkg := range pkgs {
				p := pkg.Types
				if p == nil || p.Scope() == nil || p.Scope().Len() == 0 {
					return errorf(nil, "unable to bind package %s: no types found", binding.Package)
				}

				for _, typ := range p.Scope().Names() {
					if token.IsExported(typ) {
						// Check if type is manual bindings
						_, exist := c.Bindings[typ]
						if !exist {
							pathType := fmt.Sprintf("%s.%s", p.Path(), typ)
							c.Bindings[typ] = &TypeBinding{
								Type: pathType,
							}
						}
					}
				}
			}
		}
	}

	if err := c.Casing.validate(); err != nil {
		return err
	}

	return nil
}

// ReadAndValidateConfig reads the configuration from the given file, validates
// it, and returns it.
func ReadAndValidateConfig(filename string) (*Config, error) {
	text, err := os.ReadFile(filename)
	if err != nil {
		return nil, errorf(nil, "unreadable config file %v: %v", filename, err)
	}

	var config Config
	err = yaml.UnmarshalStrict(text, &config)
	if err != nil {
		return nil, errorf(nil, "invalid config file %v: %v", filename, err)
	}

	err = config.ValidateAndFillDefaults(filepath.Dir(filename))
	if err != nil {
		return nil, errorf(nil, "invalid config file %v: %v", filename, err)
	}

	return &config, nil
}

// ReadAndValidateConfigFromDefaultLocations looks for a config file in the
// current directory, and all parent directories walking up the tree. The
// closest config file will be returned.
func ReadAndValidateConfigFromDefaultLocations() (*Config, error) {
	cfgFile, err := findCfg()
	if err != nil {
		return nil, err
	}
	return ReadAndValidateConfig(cfgFile)
}

//go:embed default_genqlient.yaml
var defaultConfig []byte

func initConfig(filename string) error {
	return os.WriteFile(filename, defaultConfig, 0o644)
}

// findCfg searches for the config file in this directory and all parents up the tree
// looking for the closest match
func findCfg() (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", errorf(nil, "unable to get working dir to findCfg: %v", err)
	}

	cfg := findCfgInDir(dir)

	for cfg == "" && dir != filepath.Dir(dir) {
		dir = filepath.Dir(dir)
		cfg = findCfgInDir(dir)
	}

	if cfg == "" {
		return "", os.ErrNotExist
	}

	return cfg, nil
}

func findCfgInDir(dir string) string {
	for _, cfgName := range cfgFilenames {
		path := pathJoin(dir, cfgName)
		if _, err := os.Stat(path); err == nil {
			return path
		}
	}
	return ""
}
