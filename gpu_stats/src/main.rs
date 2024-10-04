mod wandb_internal;

use clap::Parser;

use tonic;
use tonic::{transport::Server, Request, Response, Status};
use tonic_reflection;

use wandb_internal::record::RecordType;
use wandb_internal::{
    stats_record::StatsType,
    system_monitor_server::{SystemMonitor, SystemMonitorServer},
    GetMetadataRequest, GetStatsRequest, Record, StatsItem, StatsRecord,
};

#[derive(Parser, Debug)]
#[command(author, version, about, long_about=None)]
struct Args {
    #[arg(short, long, default_value = "50051")]
    port: i32,
}

#[derive(Debug, Default)]
pub struct SystemMonitorImpl {
    shutdown_sender: tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>,
}

#[tonic::async_trait]
impl SystemMonitor for SystemMonitorImpl {
    // tear_down takes an empty request and returns an empty response
    async fn tear_down(&self, request: Request<()>) -> Result<Response<()>, Status> {
        println!("Got a request to shutdown: {:?}", request);

        // Signal the server to shutdown
        let mut sender = self.shutdown_sender.lock().await;

        if let Some(sender) = sender.take() {
            sender.send(()).unwrap();
        }
        Ok(Response::new(()))
    }

    async fn get_stats(
        &self,
        request: Request<GetStatsRequest>,
    ) -> Result<Response<Record>, Status> {
        println!("Got a request to get stats: {:?}", request);

        // TODO: get actual stats
        let stats = vec![("gpu.0.memoryAllocated", 1.6800944010416665)];

        let stats_items: Vec<StatsItem> = stats
            .iter()
            .map(|(name, value)| StatsItem {
                key: name.to_string(),
                value_json: value.to_string(),
            })
            .collect();

        let record = Record {
            record_type: Some(RecordType::Stats(StatsRecord {
                stats_type: StatsType::System as i32,
                item: stats_items,
                ..Default::default()
            })),
            ..Default::default()
        };

        Ok(Response::new(record))
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();

    let addr = format!("[::1]:{}", args.port).parse().unwrap();

    // Create the shutdown signal channel
    let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel::<()>();

    // System monitor service
    let system_monitor = SystemMonitorImpl {
        shutdown_sender: tokio::sync::Mutex::new(Some(shutdown_sender)),
    };

    // Reflection service
    // TODO: clean up this code
    // let descriptor = "src/descriptor.bin";
    // let binding = std::fs::read(descriptor).unwrap();
    // let descriptor_bytes = binding.as_slice();

    // let reflection_service = tonic_reflection::server::Builder::configure()
    //     .register_encoded_file_descriptor_set(descriptor_bytes)
    //     .build_v1()
    //     .unwrap();

    println!("Server listening on {}", addr);

    Server::builder()
        .add_service(SystemMonitorServer::new(system_monitor))
        // .add_service(reflection_service)
        .serve_with_shutdown(addr, async {
            // Wait for the shutdown signal
            shutdown_receiver.await.ok();
            println!("Server is shutting down...");
        })
        .await?;

    Ok(())
}
