package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"
	"syscall/js"

	"github.com/wandb/wandb/nexus/server"
)

var globApiKey string

func main() {
	js.Global().Set("base64", encodeWrapper())
	js.Global().Set("wandb_login", wandb_login())
	js.Global().Set("wandb_init", wandb_init())
	js.Global().Set("wandb_finish", wandb_finish())
	js.Global().Set("wandb_log_scaler", wandb_log_scaler())
	<-make(chan bool)
}

func wandb_login() js.Func {
	return js.FuncOf(func(this js.Value, args []js.Value) interface{} {
		if len(args) == 0 {
			return wrap("", "Not enough arguments")
		}
		apiKey := args[0].String()
		globApiKey = apiKey
		return wrap("junkdoit", "")
	})
}

type Run struct {
	RunId   string `json:"id"`
	RunNum  int    `json:"_num"`
	Entity  string `json:"entity"`
	Project string `json:"project"`
	Name    string `json:"name"`
	URL     string `json:"url"`
}

func wandb_finish() js.Func {
	return js.FuncOf(func(this js.Value, args []js.Value) interface{} {
		if len(args) == 0 {
			return wrap("", "Not enough arguments")
		}
		num := args[0].Int()
		server.LibFinish(num)

		handler := js.FuncOf(func(this js.Value, args []js.Value) interface{} {
			resolve := args[0]
			go func(num int) {
				server.LibRecv(num)
				resp := wrap("finnn", "")
				resolve.Invoke(resp)
			}(num)
			return nil
		})

		promiseConstructor := js.Global().Get("Promise")
		return promiseConstructor.New(handler)
	})
}

func wandb_log_scaler() js.Func {
	return js.FuncOf(func(this js.Value, args []js.Value) interface{} {
		if len(args) != 3 {
			return wrap("", "wrong arguments")
		}
		num := args[0].Int()
		k := args[1].String()
		v := args[2].Float()
		server.LibLogScaler(num, k, v)
		return wrap("ok", "")
	})
}

func wandb_recv() js.Func {
	return js.FuncOf(func(this js.Value, args []js.Value) interface{} {
		if len(args) == 0 {
			return wrap("", "Not enough arguments")
		}
		num := args[0].Int()
		_ = server.LibRecv(num)

		return wrap("junkdoit", "")
	})
}

func wandb_init() js.Func {
	return js.FuncOf(func(this js.Value, args []js.Value) interface{} {
		base_url := "https://api.wandb.ai"
		run_id := server.ShortID(8)
		settings := &server.Settings{
			BaseURL:  base_url,
			ApiKey:   globApiKey,
			SyncFile: "something.wandb",
			NoWrite:  true,
			Offline:  false}
		num := server.LibStartSettings(settings, run_id)
		run := Run{RunId: run_id, RunNum: num}

		handler := js.FuncOf(func(this js.Value, args []js.Value) interface{} {
			resolve := args[0]
			go func(run Run) {
				got := server.LibRecv(num)
				run.Entity = got.GetRunResult().GetRun().GetEntity()
				run.Project = got.GetRunResult().GetRun().GetProject()
				run.Name = got.GetRunResult().GetRun().GetDisplayName()
				// Handle wandb server
				app_url := strings.Replace(base_url, "://api.", "://", 1)
				run.URL = fmt.Sprintf("%s/%s/%s/runs/%s", app_url, run.Entity, run.Project, run.RunId)
				server.LibRunStart(num)
				server.LibRecv(num)

				data, err := json.Marshal(run)
				if err != nil {
					panic(err)
				}
				resp := wrap(string(data), "")
				resolve.Invoke(resp)
			}(run)
			return nil
		})

		promiseConstructor := js.Global().Get("Promise")
		return promiseConstructor.New(handler)
	})
}

func encodeWrapper() js.Func {
	return js.FuncOf(func(this js.Value, args []js.Value) interface{} {
		if len(args) == 0 {
			return wrap("", "Not enough arguments")
		}
		input := args[0].String()
		return wrap(base64.StdEncoding.EncodeToString([]byte(input)), "")
	})
}

func wrap(encoded string, err string) map[string]interface{} {
	return map[string]interface{}{
		"error":   err,
		"encoded": encoded,
	}
}
