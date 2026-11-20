//go:build generate

// This program generates a property file in Go file from Unicode Character
// Database auxiliary data files. The command line arguments are as follows:
//
//  1. The name of the Unicode data file (just the filename, without extension).
//     Can be "-" (to skip) if the emoji flag is included.
//  2. The name of the locally generated Go file.
//  3. The name of the slice mapping code points to properties.
//  4. The name of the generator, for logging purposes.
//  5. (Optional) Flags, comma-separated. The following flags are available:
//     - "emojis=<property>": include the specified emoji properties (e.g.
//     "Extended_Pictographic").
//     - "gencat": include general category properties.
//     - "sections=<sections>": include only sections with the given strings
//     (comma-separated) found in the section header (must be a comment).
//     Sections end with a blank line.
//
//go:generate go run gen_properties.go auxiliary/GraphemeBreakProperty graphemeproperties.go graphemeCodePoints graphemes emojis=Extended_Pictographic
//go:generate go run gen_properties.go auxiliary/WordBreakProperty wordproperties.go workBreakCodePoints words emojis=Extended_Pictographic
//go:generate go run gen_properties.go auxiliary/SentenceBreakProperty sentenceproperties.go sentenceBreakCodePoints sentences
//go:generate go run gen_properties.go LineBreak lineproperties.go lineBreakCodePoints lines gencat
//go:generate go run gen_properties.go EastAsianWidth eastasianwidth.go eastAsianWidth eastasianwidth
//go:generate go run gen_properties.go - emojipresentation.go emojiPresentation emojipresentation emojis=Emoji_Presentation
//go:generate go run gen_properties.go DerivedCoreProperties indicconjunct.go indicConjunct indicconjunct sections=Indic_Conjunct_Break
package main

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"go/format"
	"io/ioutil"
	"iter"
	"log"
	"net/http"
	"os"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"
)

// We want to test against a specific version rather than the latest. When the
// package is upgraded to a new version, change these to generate new tests.
const (
	urlTemplate = `https://www.unicode.org/Public/18.0.0/ucd/%s.txt`
	emojiURL    = `https://unicode.org/Public/18.0.0/ucd/emoji/emoji-data.txt`
)

// The regular expression for a line containing a code point range property.
var propertyPattern = regexp.MustCompile(`^([0-9A-F]{4,6})(\.\.([0-9A-F]{4,6}))?\s*;\s*([A-Za-z0-9_]+)(; ([A-Za-z0-9_]+))?\s*#\s(.+)$`)

func main() {
	if len(os.Args) < 5 {
		fmt.Println("Not enough arguments, see code for details")
		os.Exit(1)
	}

	log.SetPrefix("gen_properties (" + os.Args[4] + "): ")
	log.SetFlags(0)

	// Parse flags.
	flags := make(map[string]string)
	if len(os.Args) >= 6 {
		for _, flag := range strings.Split(os.Args[5], ",") {
			flagFields := strings.Split(flag, "=")
			if len(flagFields) == 1 {
				flags[flagFields[0]] = "yes"
			} else {
				flags[flagFields[0]] = flagFields[1]
			}
		}
	}

	// Parse the text file and generate Go source code from it.
	var sections []string
	if s := flags["sections"]; s != "" {
		sections = strings.Split(s, ",")
	}
	_, includeGeneralCategory := flags["gencat"]
	var mainURL string
	if os.Args[1] != "-" {
		mainURL = fmt.Sprintf(urlTemplate, os.Args[1])
	}
	src, err := parse(mainURL, flags["emojis"], includeGeneralCategory, sections)
	if err != nil {
		log.Fatal(err)
	}

	// Format the Go code.
	formatted, err := format.Source([]byte(src))
	if err != nil {
		log.Fatal("gofmt:", err)
	}

	// Save it to the (local) target file.
	log.Print("Writing to ", os.Args[2])
	if err := ioutil.WriteFile(os.Args[2], formatted, 0644); err != nil {
		log.Fatal(err)
	}
}

// parse parses the Unicode Properties text files located at the given URLs and
// returns their equivalent Go source code to be used in the uniseg package. If
// emojiProperty is not an empty string, emoji code points for that emoji
// property (e.g. "Extended_Pictographic") will be included, adding to existing
// properties where they overlap. In those cases, you may pass an empty
// propertyURL to skip parsing the main properties file. If
// includeGeneralCategory is true, the Unicode General Category property will
// be extracted from the derived general category file and added to the
// properties as an extra value. If "sections" is not empty, only the specified
// sections will be included (see flags for details).
func parse(propertyURL, emojiProperty string, includeGeneralCategory bool, sections []string) (string, error) {
	if propertyURL == "" && emojiProperty == "" {
		return "", errors.New("no properties to parse")
	}

	// Temporary buffer to hold properties.
	var properties [][4]string

	// Open the first URL.
	if propertyURL != "" {
		log.Printf("Parsing %s", propertyURL)
		res, err := http.Get(propertyURL)
		if err != nil {
			return "", err
		}
		in1 := res.Body
		defer in1.Close()

		// Parse it.
		scanner := bufio.NewScanner(in1)
		num := 0
		var propertyFound bool
		inSection := len(sections) == 0
		for scanner.Scan() {
			num++
			line := strings.TrimSpace(scanner.Text())

			if strings.HasPrefix(line, "#") {
				// Comments.
				if slices.ContainsFunc(sections, func(s string) bool { return strings.Contains(line, s) }) {
					// We're starting a new (included) section.
					inSection = true
					propertyFound = false
				}
				continue // Comments do not get parsed.
			} else if line == "" {
				// Blank line.
				if len(sections) > 0 && inSection && propertyFound {
					// End of an (included) section.
					inSection = false
				}
				continue // Blank lines do not get parsed.
			}

			// Skip sections that are not included.
			if !inSection {
				continue
			}

			// Everything else must be a code point range, a property and a comment.
			from, to, property, comment, err := parseProperty(line)
			if err != nil {
				return "", fmt.Errorf("%s line %d: %v", os.Args[4], num, err)
			}
			properties = append(properties, [4]string{from, to, property, comment})
			propertyFound = true
		}
		if err := scanner.Err(); err != nil {
			return "", err
		}
	}

	// Add emoji properties if requested.
	if emojiProperty != "" {
		log.Printf("Parsing %s", emojiURL)
		res, err := http.Get(emojiURL)
		if err != nil {
			return "", err
		}
		in2 := res.Body
		defer in2.Close()

		// Parse it.
		var emojiProperties [][4]string
		scanner := bufio.NewScanner(in2)
		num := 0
		for scanner.Scan() {
			num++
			line := scanner.Text()

			// Skip comments, empty lines, and everything not containing the
			// emoji property.
			if strings.HasPrefix(line, "#") || line == "" || !strings.Contains(line, emojiProperty) {
				continue
			}

			// Everything else must be a code point range, a property, and a
			// comment.
			fromStr, toStr, property, comment, err := parseProperty(line)
			if err != nil {
				return "", fmt.Errorf("emojis line %d: %v", num, err)
			}

			emojiProperties = append(emojiProperties, [4]string{fromStr, toStr, property, comment})
		}
		if err := scanner.Err(); err != nil {
			return "", err
		}

		// Merge emoji properties into the main properties list.
		var p [][4]string
		for r := range merge(properties, emojiProperties) {
			p = append(p, [4]string{r[0], r[1], r[2] + r[3], r[4]})
		}
		properties = p
	}

	// Add general category if requested.
	if includeGeneralCategory {
		genCatURL := fmt.Sprintf(urlTemplate, "extracted/DerivedGeneralCategory")
		log.Printf("Parsing %s", genCatURL)
		res, err := http.Get(genCatURL)
		if err != nil {
			return "", err
		}
		in3 := res.Body
		defer in3.Close()

		// Parse it.
		var generalCategories [][4]string
		scanner := bufio.NewScanner(in3)
		num := 0
		for scanner.Scan() {
			num++
			line := scanner.Text()

			// Skip comments and empty lines.
			if strings.HasPrefix(line, "#") || line == "" {
				continue
			}

			// Everything else must be a code point range, a category, and a
			// comment.
			fromStr, toStr, property, comment, err := parseProperty(line)
			if err != nil {
				return "", fmt.Errorf("general category line %d: %v", num, err)
			}

			generalCategories = append(generalCategories, [4]string{fromStr, toStr, property, comment})
		}
		if err := scanner.Err(); err != nil {
			return "", err
		}

		// Merge general categories into the main properties list.
		var p [][4]string
		for r := range merge(properties, generalCategories) {
			property := r[2]
			if property == "" {
				property = "XX"
			}
			generalCategory := r[3]
			if generalCategory == "" {
				generalCategory = "None"
			}
			p = append(p, [4]string{r[0], r[1], property + ";" + generalCategory, r[4]})
		}
		properties = p
	}

	// Avoid overflow during binary search.
	if len(properties) >= 1<<31 {
		return "", errors.New("too many properties")
	}

	// Sort properties.
	sort.Slice(properties, func(i, j int) bool {
		left, _ := strconv.ParseUint(properties[i][0], 16, 64)
		right, _ := strconv.ParseUint(properties[j][0], 16, 64)
		return left < right
	})

	// Header.
	var (
		buf          bytes.Buffer
		emojiComment string
	)
	columns := 3
	if includeGeneralCategory {
		columns = 4
	}
	if emojiProperty != "" {
		emojiComment = `
// and
// ` + emojiURL + `
// ("Extended_Pictographic" only)`
	}
	buf.WriteString(`// Code generated via go generate from gen_properties.go. DO NOT EDIT.

package uniseg

// ` + os.Args[3] + ` are taken from
// ` + propertyURL + emojiComment + `
// on ` + time.Now().Format("January 2, 2006") + `. See https://www.unicode.org/license.html for the Unicode
// license agreement.
var ` + os.Args[3] + ` = [][` + strconv.Itoa(columns) + `]int{
	`)

	// Properties.
	for _, prop := range properties {
		if includeGeneralCategory {
			fields := strings.Split(prop[2], ";")
			p := fields[0]
			gc := fields[1]
			fmt.Fprintf(&buf, "{0x%s,0x%s,%s,%s}, // %s\n", prop[0], prop[1], translateProperty("pr", p), "gc"+gc, prop[3])
		} else {
			fmt.Fprintf(&buf, "{0x%s,0x%s,%s}, // %s\n", prop[0], prop[1], translateProperty("pr", prop[2]), prop[3])
		}
	}

	// Tail.
	buf.WriteString("}")

	return buf.String(), nil
}

// parseProperty parses a line of the Unicode properties text file containing a
// property for a code point range and returns it along with its comment.
func parseProperty(line string) (from, to, property, comment string, err error) {
	fields := propertyPattern.FindStringSubmatch(line)
	if fields == nil {
		err = errors.New("no property found")
		return
	}
	from = fields[1]
	to = fields[3]
	if to == "" {
		to = from
	}
	property = fields[4]
	if second := fields[6]; second != "" {
		property += second
	}
	comment = fields[7]
	return
}

// translateProperty translates a property name as used in the Unicode data file
// to a variable used in the Go code.
func translateProperty(prefix, property string) string {
	return prefix + strings.ReplaceAll(property, "_", "")
}

// merge returns an iterator over the merged properties from the first and
// second slices. The iterator yields elements of type [5]string:
//
//  1. The starting code point of the range.
//  2. The ending code point of the range.
//  3. The property value from the first slice, if present.
//  4. The property value from the second slice, if present.
//  5. The (joined) comment associated with the property.
//
// Both first and second will get sorted by their starting code points.
func merge(first, second [][4]string) iter.Seq[[5]string] {
	// indices stores range start and exclusive end points from both slices.
	// Each element contains the point, range index, start/end flag, and slice
	// index (0 for first, 1 for second).
	var indices [][4]uint64
	for i, r := range first {
		from, _ := strconv.ParseUint(r[0], 16, 64)
		to, _ := strconv.ParseUint(r[1], 16, 64)
		indices = append(indices, [4]uint64{from, uint64(i), 0, 0})
		indices = append(indices, [4]uint64{to + 1, uint64(i), 1, 0})
	}
	for i, r := range second {
		from, _ := strconv.ParseUint(r[0], 16, 64)
		to, _ := strconv.ParseUint(r[1], 16, 64)
		indices = append(indices, [4]uint64{from, uint64(i), 0, 1})
		indices = append(indices, [4]uint64{to + 1, uint64(i), 1, 1})
	}
	sort.Slice(indices, func(i, j int) bool {
		return indices[i][0] < indices[j][0]
	})

	return func(yield func([5]string) bool) {
		active := [2]int{-1, -1}
		var previous uint64
		for i := 0; i < len(indices); {
			point := indices[i][0]
			if previous < point && (active[0] >= 0 || active[1] >= 0) {
				firstProperty, secondProperty, comment := "", "", ""
				if active[0] >= 0 {
					property := first[active[0]]
					firstProperty = property[2]
					comment = property[3]
				}
				if active[1] >= 0 {
					property := second[active[1]]
					secondProperty = property[2]
					if comment != "" {
						comment += " + "
					}
					comment += property[3]
				}
				if !yield([5]string{
					fmt.Sprintf("%04X", previous),
					fmt.Sprintf("%04X", point-1),
					firstProperty,
					secondProperty,
					comment,
				}) {
					return
				}
			}

			for i < len(indices) && indices[i][0] == point {
				idx := indices[i]
				if idx[2] == 1 {
					active[idx[3]] = -1
				}
				i++
			}
			for j := i - 1; j >= 0 && indices[j][0] == point; j-- {
				idx := indices[j]
				if idx[2] == 0 {
					active[idx[3]] = int(idx[1])
				}
			}
			previous = point
		}
	}
}
