package monitor

import (
	"fmt"
	"os"
	"path/filepath"
)

// // #cgo LDFLAGS: -L. -lapple
// // #include "apple.h"
// // #include <stdlib.h>
// import "C"
// import (
// 	"encoding/json"
// 	"fmt"
// 	"unsafe"
// )

// func getStats() map[string]interface{} {
// 	cstr := C.gpuStats()
// 	defer C.free(unsafe.Pointer(cstr))

// 	jsonString := C.GoString(cstr)
// 	var result map[string]interface{}
// 	err := json.Unmarshal([]byte(jsonString), &result)
// 	if err != nil {
// 		fmt.Println(err)
// 	}

// 	return result
// }

// func callSwift() {
// 	stats := getStats()
// 	fmt.Println(stats)
// }

func callSwift() {
	ex, err := os.Executable()
	if err != nil {
		panic(err)
	}
	exPath := filepath.Dir(ex)
	fmt.Println(exPath)
}
