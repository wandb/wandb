import itertools
import json
import os
import threading
import time
from unittest import mock

import pytest
from wandb.sdk.internal.settings_static import SettingsStatic
from wandb.sdk.internal.system.assets import Trainium
from wandb.sdk.internal.system.assets.trainium import NeuronCoreStats
from wandb.sdk.internal.system.system_monitor import AssetInterface

MOCK_DATA = [
    {
        "neuron_runtime_data": [
            {
                "pid": 1337,
                "neuron_runtime_tag": "1337",
                "error": "",
                "report": {
                    "execution_stats": {
                        "period": 0.99915655,
                        "error_summary": {
                            "generic": 23654,
                            "numerical": 0,
                            "transient": 0,
                            "model": 0,
                            "runtime": 0,
                            "hardware": 0,
                        },
                        "execution_summary": {
                            "completed": 260,
                            "completed_with_err": 0,
                            "completed_with_num_err": 0,
                            "timed_out": 0,
                            "incorrect_input": 0,
                            "failed_to_queue": 0,
                        },
                        "latency_stats": {
                            "total_latency": {
                                "p0": 0.00008893013000488281,
                                "p1": 0.00009012222290039062,
                                "p100": 0.00014853477478027344,
                                "p25": 0.0000934600830078125,
                                "p50": 0.000095367431640625,
                                "p75": 0.0000972747802734375,
                                "p99": 0.00013184547424316406,
                            },
                            "device_latency": {
                                "p0": 0.00008893013000488281,
                                "p1": 0.00009012222290039062,
                                "p100": 0.00014853477478027344,
                                "p25": 0.0000934600830078125,
                                "p50": 0.000095367431640625,
                                "p75": 0.0000972747802734375,
                                "p99": 0.00013184547424316406,
                            },
                        },
                        "error": "",
                    },
                    "memory_used": {
                        "period": 0.999155887,
                        "neuron_runtime_used_bytes": {
                            "host": 610705408,
                            "neuron_device": 102298328,
                            "usage_breakdown": {
                                "host": {
                                    "application_memory": 609656832,
                                    "constants": 0,
                                    "dma_buffers": 1048576,
                                    "tensors": 0,
                                },
                                "neuroncore_memory_usage": {
                                    "0": {
                                        "constants": 196608,
                                        "model_code": 101125344,
                                        "model_shared_scratchpad": 0,
                                        "runtime_memory": 0,
                                        "tensors": 943608,
                                    },
                                    "1": {
                                        "constants": 0,
                                        "model_code": 32768,
                                        "model_shared_scratchpad": 0,
                                        "runtime_memory": 0,
                                        "tensors": 0,
                                    },
                                },
                            },
                        },
                        "loaded_models": [
                            {
                                "name": "/var/tmp/neuron-compile-cache/USER_neuroncc-2.3.0.4+864822b6b/"
                                "MODULE_13190871343506053659/MODULE_1_SyncTensorsGraph."
                                "387_13190871343506053659_ip-172-31-50-218.us-west-2.compute."
                                "internal-f20e0b6d-26102-5f0009ba48a5a/2c7ac994-4ded-40d3-bcca-e21b63234c5c/"
                                "MODU",
                                "uuid": "2b28572e7dd811edb0250e0372b2eb59",
                                "model_id": 10002,
                                "is_running": False,
                                "subgraphs": {
                                    "sg_00": {
                                        "memory_used_bytes": {
                                            "host": 20608,
                                            "neuron_device": 151936,
                                            "usage_breakdown": {
                                                "host": {
                                                    "application_memory": 20608,
                                                    "constants": 0,
                                                    "dma_buffers": 0,
                                                    "tensors": 0,
                                                },
                                                "neuron_device": {
                                                    "constants": 98304,
                                                    "model_code": 53632,
                                                    "runtime_memory": 0,
                                                    "tensors": 0,
                                                },
                                            },
                                        },
                                        "neuroncore_index": 0,
                                        "neuron_device_index": 0,
                                    }
                                },
                            },
                            {
                                "name": "/var/tmp/neuron-compile-cache/USER_neuroncc-2.3.0.4+864822b6b/"
                                "MODULE_8741580589776855152/MODULE_0_SyncTensorsGraph."
                                "315_8741580589776855152_ip-172-31-50-218.us-west-2.compute."
                                "internal-8523dc32-26102-5f0009b4d34c7/262d6ea2-e68b-4856-9a0d-d6666b04c0e9/"
                                "MODULE",
                                "uuid": "27d72f647dd811ed83b70e0372b2eb59",
                                "model_id": 10001,
                                "is_running": False,
                                "subgraphs": {
                                    "sg_00": {
                                        "memory_used_bytes": {
                                            "host": 20608,
                                            "neuron_device": 151936,
                                            "usage_breakdown": {
                                                "host": {
                                                    "application_memory": 20608,
                                                    "constants": 0,
                                                    "dma_buffers": 0,
                                                    "tensors": 0,
                                                },
                                                "neuron_device": {
                                                    "constants": 98304,
                                                    "model_code": 53632,
                                                    "runtime_memory": 0,
                                                    "tensors": 0,
                                                },
                                            },
                                        },
                                        "neuroncore_index": 0,
                                        "neuron_device_index": 0,
                                    }
                                },
                            },
                        ],
                        "error": "",
                    },
                    "neuron_runtime_vcpu_usage": {
                        "period": 0.999159827,
                        "vcpu_usage": {"user": 19.26, "system": 3.95},
                        "error": "",
                    },
                    "neuroncore_counters": {
                        "period": 0.999163146,
                        "neuroncores_in_use": {
                            "0": {"neuroncore_utilization": 1.3631567613356375},
                            "1": {"neuroncore_utilization": 0},
                        },
                        "error": "",
                    },
                },
            }
        ],
        "system_data": {
            "memory_info": {
                "period": 0.99911432,
                "memory_total_bytes": 33117732864,
                "memory_used_bytes": 11233579008,
                "swap_total_bytes": 0,
                "swap_used_bytes": 0,
                "error": "",
            },
            "neuron_hw_counters": {
                "period": 0.999080407,
                "neuron_devices": [
                    {
                        "neuron_device_index": 0,
                        "mem_ecc_corrected": 0,
                        "mem_ecc_uncorrected": 0,
                        "sram_ecc_uncorrected": 0,
                        "sram_ecc_corrected": 0,
                    }
                ],
                "error": "",
            },
            "vcpu_usage": {
                "period": 0.999094871,
                "average_usage": {
                    "user": 16.99,
                    "nice": 0,
                    "system": 2.94,
                    "idle": 80.08,
                    "io_wait": 0,
                    "irq": 0,
                    "soft_irq": 0,
                },
                "usage_data": {
                    "0": {
                        "user": 17.53,
                        "nice": 0,
                        "system": 3.09,
                        "idle": 79.38,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "1": {
                        "user": 20.62,
                        "nice": 0,
                        "system": 2.06,
                        "idle": 77.32,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "2": {
                        "user": 17,
                        "nice": 0,
                        "system": 3,
                        "idle": 80,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "3": {
                        "user": 19.59,
                        "nice": 0,
                        "system": 2.06,
                        "idle": 78.35,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "4": {
                        "user": 13.27,
                        "nice": 0,
                        "system": 4.08,
                        "idle": 82.65,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "5": {
                        "user": 19.19,
                        "nice": 0,
                        "system": 3.03,
                        "idle": 77.78,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "6": {
                        "user": 13.68,
                        "nice": 0,
                        "system": 1.05,
                        "idle": 85.26,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "7": {
                        "user": 14.58,
                        "nice": 0,
                        "system": 3.13,
                        "idle": 82.29,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                },
                "context_switch_count": 84801,
                "error": "",
            },
        },
        "instance_info": {
            "instance_name": "",
            "instance_id": "i-01db7a16f4c054239",
            "instance_type": "trn1.2xlarge",
            "instance_availability_zone": "us-west-2d",
            "instance_availability_zone_id": "usw2-az4",
            "instance_region": "us-west-2",
            "ami_id": "ami-0ceecbb0f30a902a6",
            "subnet_id": "subnet-011289cb54b7c352a",
            "error": "",
        },
        "neuron_hardware_info": {
            "neuron_device_count": 1,
            "neuroncore_per_device_count": 2,
            "error": "",
        },
    },
    {
        "neuron_runtime_data": [
            {
                "pid": 16851,
                "neuron_runtime_tag": "16851",
                "error": "",
                "report": {
                    "execution_stats": {
                        "period": 1.00054434,
                        "error_summary": {
                            "generic": 23692,
                            "numerical": 0,
                            "transient": 0,
                            "model": 0,
                            "runtime": 0,
                            "hardware": 0,
                        },
                        "execution_summary": {
                            "completed": 260,
                            "completed_with_err": 0,
                            "completed_with_num_err": 0,
                            "timed_out": 0,
                            "incorrect_input": 0,
                            "failed_to_queue": 0,
                        },
                        "latency_stats": {
                            "total_latency": {
                                "p0": 0.000087738037109375,
                                "p1": 0.00009036064147949219,
                                "p100": 0.00013518333435058594,
                                "p25": 0.0000934600830078125,
                                "p50": 0.000095367431640625,
                                "p75": 0.00009775161743164062,
                                "p99": 0.00012087821960449219,
                            },
                            "device_latency": {
                                "p0": 0.000087738037109375,
                                "p1": 0.00009036064147949219,
                                "p100": 0.00013518333435058594,
                                "p25": 0.0000934600830078125,
                                "p50": 0.000095367431640625,
                                "p75": 0.00009775161743164062,
                                "p99": 0.00012087821960449219,
                            },
                        },
                        "error": "",
                    },
                    "memory_used": {
                        "period": 1.000537856,
                        "neuron_runtime_used_bytes": {
                            "host": 611491840,
                            "neuron_device": 101876188,
                            "usage_breakdown": {
                                "host": {
                                    "application_memory": 610443264,
                                    "constants": 0,
                                    "dma_buffers": 1048576,
                                    "tensors": 0,
                                },
                                "neuroncore_memory_usage": {
                                    "0": {
                                        "constants": 196608,
                                        "model_code": 101125344,
                                        "model_shared_scratchpad": 0,
                                        "runtime_memory": 0,
                                        "tensors": 521468,
                                    },
                                    "1": {
                                        "constants": 0,
                                        "model_code": 32768,
                                        "model_shared_scratchpad": 0,
                                        "runtime_memory": 0,
                                        "tensors": 0,
                                    },
                                },
                            },
                        },
                        "loaded_models": [
                            {
                                "name": "/var/tmp/neuron-compile-cache/USER_neuroncc-2.3.0.4+864822b6b/"
                                "MODULE_8741580589776855152/MODULE_0_SyncTensorsGraph."
                                "315_8741580589776855152_ip-172-31-50-218.us-west-2.compute."
                                "internal-8523dc32-26102-5f0009b4d34c7/262d6ea2-e68b-4856-9a0d-d6666b04c0e9/"
                                "MODULE",
                                "uuid": "27d72f647dd811ed83b70e0372b2eb59",
                                "model_id": 10001,
                                "is_running": False,
                                "subgraphs": {
                                    "sg_00": {
                                        "memory_used_bytes": {
                                            "host": 20608,
                                            "neuron_device": 151936,
                                            "usage_breakdown": {
                                                "host": {
                                                    "application_memory": 20608,
                                                    "constants": 0,
                                                    "dma_buffers": 0,
                                                    "tensors": 0,
                                                },
                                                "neuron_device": {
                                                    "constants": 98304,
                                                    "model_code": 53632,
                                                    "runtime_memory": 0,
                                                    "tensors": 0,
                                                },
                                            },
                                        },
                                        "neuroncore_index": 0,
                                        "neuron_device_index": 0,
                                    }
                                },
                            },
                            {
                                "name": "/var/tmp/neuron-compile-cache/USER_neuroncc-2.3.0.4+864822b6b/"
                                "MODULE_13190871343506053659/MODULE_1_SyncTensorsGraph."
                                "387_13190871343506053659_ip-172-31-50-218.us-west-2.compute."
                                "internal-f20e0b6d-26102-5f0009ba48a5a/2c7ac994-4ded-40d3-bcca-e21b63234c5c/"
                                "MODU",
                                "uuid": "2b28572e7dd811edb0250e0372b2eb59",
                                "model_id": 10002,
                                "is_running": False,
                                "subgraphs": {
                                    "sg_00": {
                                        "memory_used_bytes": {
                                            "host": 20608,
                                            "neuron_device": 151936,
                                            "usage_breakdown": {
                                                "host": {
                                                    "application_memory": 20608,
                                                    "constants": 0,
                                                    "dma_buffers": 0,
                                                    "tensors": 0,
                                                },
                                                "neuron_device": {
                                                    "constants": 98304,
                                                    "model_code": 53632,
                                                    "runtime_memory": 0,
                                                    "tensors": 0,
                                                },
                                            },
                                        },
                                        "neuroncore_index": 0,
                                        "neuron_device_index": 0,
                                    }
                                },
                            },
                        ],
                        "error": "",
                    },
                    "neuron_runtime_vcpu_usage": {
                        "period": 1.000535217,
                        "vcpu_usage": {"user": 18.99, "system": 3.9},
                        "error": "",
                    },
                    "neuroncore_counters": {
                        "period": 1.000533415,
                        "neuroncores_in_use": {
                            "0": {"neuroncore_utilization": 1.3560819560861623},
                            "1": {"neuroncore_utilization": 0},
                        },
                        "error": "",
                    },
                },
            }
        ],
        "system_data": {
            "memory_info": {
                "period": 1.00043401,
                "memory_total_bytes": 33117732864,
                "memory_used_bytes": 11234598912,
                "swap_total_bytes": 0,
                "swap_used_bytes": 0,
                "error": "",
            },
            "neuron_hw_counters": {
                "period": 1.000472804,
                "neuron_devices": [
                    {
                        "neuron_device_index": 0,
                        "mem_ecc_corrected": 0,
                        "mem_ecc_uncorrected": 0,
                        "sram_ecc_uncorrected": 0,
                        "sram_ecc_corrected": 0,
                    }
                ],
                "error": "",
            },
            "vcpu_usage": {
                "period": 1.00045308,
                "average_usage": {
                    "user": 17.48,
                    "nice": 0,
                    "system": 3.52,
                    "idle": 78.99,
                    "io_wait": 0,
                    "irq": 0,
                    "soft_irq": 0,
                },
                "usage_data": {
                    "0": {
                        "user": 14.43,
                        "nice": 0,
                        "system": 2.06,
                        "idle": 83.51,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "1": {
                        "user": 17,
                        "nice": 0,
                        "system": 3,
                        "idle": 80,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "2": {
                        "user": 12.5,
                        "nice": 0,
                        "system": 3.13,
                        "idle": 84.38,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "3": {
                        "user": 17.17,
                        "nice": 0,
                        "system": 4.04,
                        "idle": 78.79,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "4": {
                        "user": 20.19,
                        "nice": 0,
                        "system": 4.81,
                        "idle": 75,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "5": {
                        "user": 24.27,
                        "nice": 0,
                        "system": 4.85,
                        "idle": 70.87,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "6": {
                        "user": 20,
                        "nice": 0,
                        "system": 3,
                        "idle": 77,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "7": {
                        "user": 14,
                        "nice": 0,
                        "system": 4,
                        "idle": 82,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                },
                "context_switch_count": 84786,
                "error": "",
            },
        },
        "instance_info": {
            "instance_name": "",
            "instance_id": "i-01db7a16f4c054239",
            "instance_type": "trn1.2xlarge",
            "instance_availability_zone": "us-west-2d",
            "instance_availability_zone_id": "usw2-az4",
            "instance_region": "us-west-2",
            "ami_id": "ami-0ceecbb0f30a902a6",
            "subnet_id": "subnet-011289cb54b7c352a",
            "error": "",
        },
        "neuron_hardware_info": {
            "neuron_device_count": 1,
            "neuroncore_per_device_count": 2,
            "error": "",
        },
    },
    {
        "neuron_runtime_data": [
            {
                "pid": 16851,
                "neuron_runtime_tag": "16851",
                "error": "",
                "report": {
                    "execution_stats": {
                        "period": 0.9994908,
                        "error_summary": {
                            "generic": 23749,
                            "numerical": 0,
                            "transient": 0,
                            "model": 0,
                            "runtime": 0,
                            "hardware": 0,
                        },
                        "execution_summary": {
                            "completed": 260,
                            "completed_with_err": 0,
                            "completed_with_num_err": 0,
                            "timed_out": 0,
                            "incorrect_input": 0,
                            "failed_to_queue": 0,
                        },
                        "latency_stats": {
                            "total_latency": {
                                "p0": 0.00009036064147949219,
                                "p1": 0.00009036064147949219,
                                "p100": 0.00013899803161621094,
                                "p25": 0.00009369850158691406,
                                "p50": 0.00009512901306152344,
                                "p75": 0.0000972747802734375,
                                "p99": 0.0001285076141357422,
                            },
                            "device_latency": {
                                "p0": 0.00009036064147949219,
                                "p1": 0.00009036064147949219,
                                "p100": 0.00013899803161621094,
                                "p25": 0.00009369850158691406,
                                "p50": 0.00009512901306152344,
                                "p75": 0.0000972747802734375,
                                "p99": 0.0001285076141357422,
                            },
                        },
                        "error": "",
                    },
                    "memory_used": {
                        "period": 0.999495099,
                        "neuron_runtime_used_bytes": {
                            "host": 612179968,
                            "neuron_device": 102298328,
                            "usage_breakdown": {
                                "host": {
                                    "application_memory": 611131392,
                                    "constants": 0,
                                    "dma_buffers": 1048576,
                                    "tensors": 0,
                                },
                                "neuroncore_memory_usage": {
                                    "0": {
                                        "constants": 196608,
                                        "model_code": 101125344,
                                        "model_shared_scratchpad": 0,
                                        "runtime_memory": 0,
                                        "tensors": 943608,
                                    },
                                    "1": {
                                        "constants": 0,
                                        "model_code": 32768,
                                        "model_shared_scratchpad": 0,
                                        "runtime_memory": 0,
                                        "tensors": 0,
                                    },
                                },
                            },
                        },
                        "loaded_models": [
                            {
                                "name": "/var/tmp/neuron-compile-cache/USER_neuroncc-2.3.0.4+864822b6b/"
                                "MODULE_8741580589776855152/MODULE_0_SyncTensorsGraph."
                                "315_8741580589776855152_ip-172-31-50-218.us-west-2.compute."
                                "internal-8523dc32-26102-5f0009b4d34c7/262d6ea2-e68b-4856-9a0d-d6666b04c0e9/"
                                "MODULE",
                                "uuid": "27d72f647dd811ed83b70e0372b2eb59",
                                "model_id": 10001,
                                "is_running": False,
                                "subgraphs": {
                                    "sg_00": {
                                        "memory_used_bytes": {
                                            "host": 20608,
                                            "neuron_device": 151936,
                                            "usage_breakdown": {
                                                "host": {
                                                    "application_memory": 20608,
                                                    "constants": 0,
                                                    "dma_buffers": 0,
                                                    "tensors": 0,
                                                },
                                                "neuron_device": {
                                                    "constants": 98304,
                                                    "model_code": 53632,
                                                    "runtime_memory": 0,
                                                    "tensors": 0,
                                                },
                                            },
                                        },
                                        "neuroncore_index": 0,
                                        "neuron_device_index": 0,
                                    }
                                },
                            },
                            {
                                "name": "/var/tmp/neuron-compile-cache/USER_neuroncc-2.3.0.4+864822b6b/"
                                "MODULE_13190871343506053659/MODULE_1_SyncTensorsGraph."
                                "387_13190871343506053659_ip-172-31-50-218.us-west-2.compute."
                                "internal-f20e0b6d-26102-5f0009ba48a5a/2c7ac994-4ded-40d3-bcca-e21b63234c5c/"
                                "MODU",
                                "uuid": "2b28572e7dd811edb0250e0372b2eb59",
                                "model_id": 10002,
                                "is_running": False,
                                "subgraphs": {
                                    "sg_00": {
                                        "memory_used_bytes": {
                                            "host": 20608,
                                            "neuron_device": 151936,
                                            "usage_breakdown": {
                                                "host": {
                                                    "application_memory": 20608,
                                                    "constants": 0,
                                                    "dma_buffers": 0,
                                                    "tensors": 0,
                                                },
                                                "neuron_device": {
                                                    "constants": 98304,
                                                    "model_code": 53632,
                                                    "runtime_memory": 0,
                                                    "tensors": 0,
                                                },
                                            },
                                        },
                                        "neuroncore_index": 0,
                                        "neuron_device_index": 0,
                                    }
                                },
                            },
                        ],
                        "error": "",
                    },
                    "neuron_runtime_vcpu_usage": {
                        "period": 0.999548663,
                        "vcpu_usage": {"user": 19.44, "system": 3.96},
                        "error": "",
                    },
                    "neuroncore_counters": {
                        "period": 0.999577264,
                        "neuroncores_in_use": {
                            "0": {"neuroncore_utilization": 1.3128372400154966},
                            "1": {"neuroncore_utilization": 0},
                        },
                        "error": "",
                    },
                },
            }
        ],
        "system_data": {
            "memory_info": {
                "period": 0.999548385,
                "memory_total_bytes": 33117732864,
                "memory_used_bytes": 11236286464,
                "swap_total_bytes": 0,
                "swap_used_bytes": 0,
                "error": "",
            },
            "neuron_hw_counters": {
                "period": 0.999553189,
                "neuron_devices": [
                    {
                        "neuron_device_index": 0,
                        "mem_ecc_corrected": 0,
                        "mem_ecc_uncorrected": 0,
                        "sram_ecc_uncorrected": 0,
                        "sram_ecc_corrected": 0,
                    }
                ],
                "error": "",
            },
            "vcpu_usage": {
                "period": 0.999554717,
                "average_usage": {
                    "user": 16.73,
                    "nice": 0,
                    "system": 3.07,
                    "idle": 80.2,
                    "io_wait": 0,
                    "irq": 0,
                    "soft_irq": 0,
                },
                "usage_data": {
                    "0": {
                        "user": 20.62,
                        "nice": 0,
                        "system": 2.06,
                        "idle": 77.32,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "1": {
                        "user": 12.12,
                        "nice": 0,
                        "system": 4.04,
                        "idle": 83.84,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "2": {
                        "user": 20.62,
                        "nice": 0,
                        "system": 3.09,
                        "idle": 76.29,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "3": {
                        "user": 13.83,
                        "nice": 0,
                        "system": 3.19,
                        "idle": 82.98,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "4": {
                        "user": 16.33,
                        "nice": 0,
                        "system": 3.06,
                        "idle": 80.61,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "5": {
                        "user": 13.54,
                        "nice": 0,
                        "system": 3.13,
                        "idle": 83.33,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "6": {
                        "user": 22.64,
                        "nice": 0,
                        "system": 3.77,
                        "idle": 73.58,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                    "7": {
                        "user": 13.54,
                        "nice": 0,
                        "system": 2.08,
                        "idle": 84.38,
                        "io_wait": 0,
                        "irq": 0,
                        "soft_irq": 0,
                    },
                },
                "context_switch_count": 84809,
                "error": "",
            },
        },
        "instance_info": {
            "instance_name": "",
            "instance_id": "i-01db7a16f4c054239",
            "instance_type": "trn1.2xlarge",
            "instance_availability_zone": "us-west-2d",
            "instance_availability_zone_id": "usw2-az4",
            "instance_region": "us-west-2",
            "ami_id": "ami-0ceecbb0f30a902a6",
            "subnet_id": "subnet-011289cb54b7c352a",
            "error": "",
        },
        "neuron_hardware_info": {
            "neuron_device_count": 1,
            "neuroncore_per_device_count": 2,
            "error": "",
        },
    },
]


def neuron_monitor_mock(self: NeuronCoreStats):
    """Generate a stream of mock raw data for NeuronCoreStats to sample."""
    self.write_neuron_monitor_config()

    for data in itertools.cycle(MOCK_DATA):
        if self.shutdown_event.is_set():
            break

        raw_data = json.dumps(data).encode()

        self.raw_samples.append(raw_data)

        # this mimics the real neuron-monitor that can't go below 1 second:
        self.shutdown_event.wait(1)


def trainium_asset(test_settings) -> AssetInterface:
    interface = AssetInterface()
    settings = SettingsStatic(
        test_settings(
            dict(
                _stats_sample_rate_seconds=1,
                _stats_samples_to_average=1,
                _stats_pid=1337,
            )
        ).make_static()
    )
    shutdown_event = threading.Event()

    trainium = Trainium(
        interface=interface,
        settings=settings,
        shutdown_event=shutdown_event,
    )

    assert not trainium.is_available()

    trainium.start()

    # wait for the mock data to be processed indefinitely,
    # until the test times out in the worst case
    while interface.metrics_queue.empty():
        time.sleep(0.1)

    shutdown_event.set()
    trainium.finish()

    assert not interface.metrics_queue.empty()
    assert not interface.telemetry_queue.empty()

    return interface


@pytest.mark.timeout(30)
def test_trainium(test_settings):
    with mock.patch.multiple(
        "wandb.sdk.internal.system.assets.trainium.NeuronCoreStats",
        neuron_monitor=neuron_monitor_mock,
    ):
        interface = trainium_asset(test_settings)
        metrics = interface.metrics_queue.get()
        assert len(metrics) == 18


@pytest.mark.timeout(30)
@pytest.mark.parametrize("local_rank", ("0", "1"))
def test_trainium_torchrun(test_settings, local_rank):
    with mock.patch.multiple(
        "wandb.sdk.internal.system.assets.trainium.NeuronCoreStats",
        neuron_monitor=neuron_monitor_mock,
    ), mock.patch.dict(
        os.environ,
        {
            "LOCAL_RANK": local_rank,
        },
    ):
        interface = trainium_asset(test_settings)
        metrics = interface.metrics_queue.get()
        assert len(metrics) == 12
        assert (
            len([key for key in metrics.keys() if key.startswith(f"trn.{local_rank}")])
            == 6
        )
