import torch

assert torch.cuda.is_available(), "CUDA not available!"

print("CUDA available:", torch.cuda.is_available())
print("CUDA device count:", torch.cuda.device_count())
print("CUDA current device:", torch.cuda.current_device())
print("CUDA device name:", torch.cuda.get_device_name(0))
print("CUDA device properties:", torch.cuda.get_device_properties(0))
print("CUDA device memory:", torch.cuda.get_device_capability(0))
