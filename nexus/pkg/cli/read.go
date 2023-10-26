package cli

import (
    "encoding/csv"
    // "fmt"
    "io"
    "bufio"
    "log"
    "os"
	"github.com/wandb/wandb/nexus/pkg/gowandb"
)

func ReadFromInput(stream *gowandb.Stream) {
	// fmt.Printf("readinput\n")
	reader := bufio.NewReader(os.Stdin)

	// read csv values using csv.Reader
    csvReader := csv.NewReader(reader)
	var header []string
    for {
        rec, err := csvReader.Read()
        if err == io.EOF {
            break
        }
        if err != nil {
            log.Fatal(err)
        }
		if header == nil {
			header = rec
			continue
		}
        // do something with read line
        // fmt.Printf("%+v\n", rec)
		data := make(gowandb.History)
		for i, v := range rec {
			data[header[i]] = v
		}
		stream.Log(data)
    }
}
