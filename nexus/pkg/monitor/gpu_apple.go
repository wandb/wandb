package monitor

// #cgo LDFLAGS: -L. -lapple
// #include "apple.h"
// #include <stdlib.h>
import "C"
import (
	"encoding/json"
	"fmt"
	"unsafe"
)

func getStats() map[string]interface{} {
	cstr := C.gpuStats()
	defer C.free(unsafe.Pointer(cstr))

	jsonString := C.GoString(cstr)
	var result map[string]interface{}
	err := json.Unmarshal([]byte(jsonString), &result)
	if err != nil {
		fmt.Println(err)
	}

	return result
}

func callSwift() {
	stats := getStats()
	fmt.Println(stats)
}
