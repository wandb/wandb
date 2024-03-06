package server_test

// func BenchmarkStreamStart(b *testing.B) {
// 	// use a temporary file for the sync file
// 	settings := service.Settings{
// 		SyncFile: &wrapperspb.StringValue{Value: "test"},
// 	}
// 	for i := 0; i < b.N; i++ {
// 		streamId := fmt.Sprintf("stream-%d", i)
// 		// Create a Stream instance with your desired settings and handler implementation
// 		stream := server.NewStream(
// 			// context.Context
// 			context.Background(),
// 			// service.Settings
// 			&settings,
// 			// streamId string
// 			streamId,
// 		)

// 		// Run the Start method
// 		stream.Start()

// 		// Wait for the Stream to finish (assuming you have a way to signal completion)
// 		// This is just for the purpose of benchmarking; in a real-world scenario, you may need to handle synchronization differently.
// 		stream.Close()
// 	}
// }
