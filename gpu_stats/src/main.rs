mod gpu_apple;
mod gpu_apple_sources;
mod wandb_internal;

use clap::Parser;

use tokio_stream;
use tonic;
use tonic::{transport::Server, Request, Response, Status};
use tonic_reflection;

use gpu_apple::ThreadSafeSampler;
use wandb_internal::record::RecordType;
use wandb_internal::{
    stats_record::StatsType,
    system_monitor_server::{SystemMonitor, SystemMonitorServer},
    GetMetadataRequest, GetStatsRequest, Record, StatsItem, StatsRecord,
};

#[derive(Parser, Debug)]
#[command(author, version, about, long_about=None)]
struct Args {
    #[arg(short, long)]
    portfile: String,
}

#[derive(Default)]
pub struct SystemMonitorImpl {
    shutdown_sender: tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>,
    // apple_sampler: Option<Sampler>,
    sampler: Option<ThreadSafeSampler>,
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

        // Initialize an empty vector to store all metrics
        let mut all_metrics = Vec::new();

        // Gather Apple metrics if sampler is available
        if let Some(sampler) = &self.sampler {
            match sampler.get_metrics().await {
                Ok(apple_stats) => {
                    let apple_metrics = ThreadSafeSampler::metrics_to_vec(apple_stats);
                    println!("Apple metrics: {:?}", apple_metrics);
                    all_metrics.extend(apple_metrics);
                }
                Err(e) => {
                    println!("Failed to get Apple metrics: {}", e);
                }
            }
        }

        let stats_items: Vec<StatsItem> = all_metrics
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

    // Bind only to the loopback interface
    let addr = (std::net::Ipv4Addr::LOCALHOST, 0);
    let listener = tokio::net::TcpListener::bind(addr).await?;

    // Create the shutdown signal channel
    let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel::<()>();

    // System monitor service
    let system_monitor = SystemMonitorImpl {
        shutdown_sender: tokio::sync::Mutex::new(Some(shutdown_sender)),
        sampler: Some(ThreadSafeSampler::new()?),
    };

    // TODO: Reflection service
    let descriptor = "/Users/dimaduev/dev/sdk/gpu_stats/src/descriptor.bin";
    let binding = std::fs::read(descriptor).unwrap();
    let descriptor_bytes = binding.as_slice();

    let reflection_service = tonic_reflection::server::Builder::configure()
        .register_encoded_file_descriptor_set(descriptor_bytes)
        .build_v1()
        .unwrap();

    let local_addr = listener.local_addr()?;

    // Write the port to the portfile
    std::fs::write(&args.portfile, local_addr.port().to_string())?;

    println!("System metrics service listening on {}", local_addr);

    Server::builder()
        .add_service(SystemMonitorServer::new(system_monitor))
        .add_service(reflection_service)
        .serve_with_incoming_shutdown(
            tokio_stream::wrappers::TcpListenerStream::new(listener),
            async {
                // Wait for the shutdown signal
                shutdown_receiver.await.ok();
                println!("Server is shutting down...");
            },
        )
        .await?;

    Ok(())
}
