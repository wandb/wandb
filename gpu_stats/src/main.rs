mod gpu_apple;
mod gpu_apple_sources;
mod wandb_internal;

use clap::Parser;

use tonic;
use tonic::{transport::Server, Request, Response, Status};
use tonic_reflection;

use gpu_apple::{Metrics, Sampler};
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

use std::sync::mpsc::{channel, Receiver, Sender};
use tokio::sync::oneshot;

// Define a specific error type for our sampler
#[derive(Debug)]
pub struct SamplerError(String);

impl std::fmt::Display for SamplerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Sampler error: {}", self.0)
    }
}

impl std::error::Error for SamplerError {}

enum SamplerCommand {
    GetMetrics(oneshot::Sender<Result<Metrics, SamplerError>>),
    Shutdown,
}

pub struct ThreadSafeSampler {
    command_sender: Sender<SamplerCommand>,
}

impl ThreadSafeSampler {
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let (command_sender, command_receiver) = channel();

        std::thread::spawn(move || {
            sampler_thread(command_receiver);
        });

        Ok(Self { command_sender })
    }

    pub async fn get_metrics(&self) -> Result<Metrics, Box<dyn std::error::Error>> {
        let (response_sender, response_receiver) = oneshot::channel();
        self.command_sender
            .send(SamplerCommand::GetMetrics(response_sender))
            .map_err(|e| Box::new(SamplerError(e.to_string())) as Box<dyn std::error::Error>)?;

        response_receiver
            .await
            .map_err(|e| Box::new(SamplerError(e.to_string())) as Box<dyn std::error::Error>)?
            .map_err(|e| Box::new(e) as Box<dyn std::error::Error>)
    }
}

impl Drop for ThreadSafeSampler {
    fn drop(&mut self) {
        let _ = self.command_sender.send(SamplerCommand::Shutdown);
    }
}

fn sampler_thread(receiver: Receiver<SamplerCommand>) {
    let mut sampler = match Sampler::new() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Failed to create Sampler: {}", e);
            return;
        }
    };

    for cmd in receiver {
        match cmd {
            SamplerCommand::GetMetrics(response) => {
                let result = sampler
                    .get_metrics(1)
                    .map_err(|e| SamplerError(e.to_string()));
                let _ = response.send(result);
            }
            SamplerCommand::Shutdown => break,
        }
    }
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

        let apple_stats = self
            .sampler
            .as_ref()
            .ok_or_else(|| Status::internal("Sampler not initialized"))?
            .get_metrics()
            .await
            .map_err(|e| Status::internal(format!("Failed to get metrics: {}", e)))?;

        println!("Apple stats: {:?}", apple_stats);

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
        sampler: Some(ThreadSafeSampler::new()?),
    };

    // Reflection service
    // TODO: clean up this code
    let descriptor = "/Users/dimaduev/dev/sdk/gpu_stats/src/descriptor.bin";
    let binding = std::fs::read(descriptor).unwrap();
    let descriptor_bytes = binding.as_slice();

    let reflection_service = tonic_reflection::server::Builder::configure()
        .register_encoded_file_descriptor_set(descriptor_bytes)
        .build_v1()
        .unwrap();

    println!("System metrics service listening on {}", addr);

    Server::builder()
        .add_service(SystemMonitorServer::new(system_monitor))
        .add_service(reflection_service)
        .serve_with_shutdown(addr, async {
            // Wait for the shutdown signal
            shutdown_receiver.await.ok();
            println!("Server is shutting down...");
        })
        .await?;

    Ok(())
}
