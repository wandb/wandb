"""Run name generator for W&B runs based on config analysis."""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import click

from wandb.apis.public import Api, Run


class RunNameGenerator:
    """Generate meaningful run names from W&B run configurations."""
    
    def __init__(
        self,
        api: Any,
        entity: str,
        project: str,
        max_name_length: int = 50,
        verbose: bool = False
    ):
        """Initialize the run name generator.
        
        Args:
            api: W&B API client
            entity: Entity name
            project: Project name
            max_name_length: Maximum length of generated names
            verbose: Whether to show detailed analysis
        """
        self.api = api
        self.entity = entity
        self.project = project
        self.max_name_length = max_name_length
        self.verbose = verbose
        
        # Initialize public API for run data access
        self.public_api = Api()
        
        # Common parameter names that are often important for run naming
        self.important_params = {
            'model', 'model_name', 'model_type', 'architecture', 'arch',
            'learning_rate', 'lr', 'batch_size', 'epochs', 'epoch',
            'optimizer', 'dataset', 'data', 'experiment', 'task',
            'loss', 'loss_function', 'activation', 'dropout',
            'hidden_size', 'num_layers', 'seq_length', 'vocab_size',
            'temperature', 'top_k', 'top_p', 'seed', 'variant'
        }
    
    def generate_name(self, run_id: str, previous_runs_count: int = 5) -> str:
        """Generate a meaningful name for the run.
        
        Args:
            run_id: The run ID to generate a name for
            previous_runs_count: Number of previous runs to analyze for context
            
        Returns:
            Generated run name
        """
        # Get the target run
        target_run = self._get_run(run_id)
        if not target_run:
            raise ValueError(f"Run {run_id} not found")
            
        if self.verbose:
            click.echo(f"Analyzing run: {target_run.name}")
            click.echo(f"Current name: {target_run.name}")
        
        # Extract key parameters from config
        config = target_run.config
        if self.verbose:
            click.echo(f"Config keys: {list(config.keys()) if config else 'None'}")
        
        # Get previous runs for context if requested
        previous_runs = []
        if previous_runs_count > 0:
            previous_runs = self._get_previous_runs(target_run, previous_runs_count)
            if self.verbose:
                click.echo(f"Analyzing {len(previous_runs)} previous runs for context")
        
        # Generate name based on config analysis
        name = self._generate_name_from_config(config, target_run, previous_runs)
        
        # Ensure name doesn't exceed max length
        if len(name) > self.max_name_length:
            name = name[:self.max_name_length-3] + "..."
            
        return name
    
    def _get_run(self, run_id: str) -> Optional[Run]:
        """Get a run by ID."""
        try:
            return self.public_api.run(f"{self.entity}/{self.project}/{run_id}")
        except Exception as e:
            if self.verbose:
                click.echo(f"Error fetching run {run_id}: {e}")
            return None
    
    def _get_previous_runs(self, target_run: Run, count: int) -> List[Run]:
        """Get previous runs for context analysis."""
        try:
            # Get recent runs from the project
            runs = self.public_api.runs(
                f"{self.entity}/{self.project}",
                filters={"state": "finished"},
                order="-created_at"
            )
            
            previous_runs = []
            for run in runs:
                if run.id != target_run.id and len(previous_runs) < count:
                    previous_runs.append(run)
                if len(previous_runs) >= count:
                    break
            
            return previous_runs
        except Exception as e:
            if self.verbose:
                click.echo(f"Error fetching previous runs: {e}")
            return []
    
    def _generate_name_from_config(self, config: Dict[str, Any], target_run: Run, previous_runs: List[Run]) -> str:
        """Generate a name based on config analysis."""
        if not config:
            return self._generate_fallback_name(target_run)
        
        # Extract important parameters
        important_values = self._extract_important_params(config)
        
        if self.verbose:
            click.echo(f"Important parameters: {important_values}")
        
        # Try different naming strategies
        name_parts = []
        
        # Strategy 1: Model/Architecture based naming
        model_name = self._get_model_identifier(important_values)
        if model_name:
            name_parts.append(model_name)
        
        # Strategy 2: Key hyperparameters
        key_params = self._get_key_hyperparameters(important_values)
        if key_params:
            name_parts.extend(key_params)
        
        # Strategy 3: Experiment variant (if this differs from previous runs)
        if previous_runs:
            variant = self._get_experiment_variant(important_values, previous_runs)
            if variant:
                name_parts.append(variant)
        
        # Strategy 4: Task/Dataset identifier
        task_info = self._get_task_identifier(important_values)
        if task_info:
            name_parts.append(task_info)
        
        # Combine parts into a meaningful name
        if name_parts:
            name = "-".join(name_parts)
            # Clean up the name
            name = self._clean_name(name)
            return name
        
        return self._generate_fallback_name(target_run)
    
    def _extract_important_params(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters that are likely important for naming."""
        important_values = {}
        
        # Flatten nested configs
        flat_config = self._flatten_config(config)
        
        for key, value in flat_config.items():
            key_lower = key.lower()
            
            # Check if this key matches any important parameter patterns
            for param in self.important_params:
                if param in key_lower or key_lower in param:
                    important_values[key] = value
                    break
        
        return important_values
    
    def _flatten_config(self, config: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
        """Flatten nested configuration dictionaries."""
        items = []
        for k, v in config.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_config(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)
    
    def _get_model_identifier(self, important_values: Dict[str, Any]) -> Optional[str]:
        """Extract model/architecture identifier."""
        model_keys = ['model', 'model_name', 'model_type', 'architecture', 'arch']
        
        for key in model_keys:
            for param_key, value in important_values.items():
                if key in param_key.lower():
                    return str(value).replace('_', '-')
        
        return None
    
    def _get_key_hyperparameters(self, important_values: Dict[str, Any]) -> List[str]:
        """Extract key hyperparameters for naming."""
        key_params = []
        
        # Learning rate
        lr_value = None
        lr_keys = ['learning_rate', 'lr']
        for key in lr_keys:
            if lr_value is not None:
                break
            for param_key, value in important_values.items():
                if key in param_key.lower():
                    if isinstance(value, (int, float)):
                        key_params.append(f"lr{value}")
                        lr_value = value
                    break
        
        # Batch size
        bs_value = None
        batch_keys = ['batch_size', 'batch']
        for key in batch_keys:
            if bs_value is not None:
                break
            for param_key, value in important_values.items():
                if key in param_key.lower():
                    if isinstance(value, int):
                        key_params.append(f"bs{value}")
                        bs_value = value
                    break
        
        # Epochs
        ep_value = None
        epoch_keys = ['epochs', 'epoch', 'num_epochs']
        for key in epoch_keys:
            if ep_value is not None:
                break
            for param_key, value in important_values.items():
                if key in param_key.lower():
                    if isinstance(value, int):
                        key_params.append(f"ep{value}")
                        ep_value = value
                    break
        
        return key_params
    
    def _get_experiment_variant(self, important_values: Dict[str, Any], previous_runs: List[Run]) -> Optional[str]:
        """Identify experiment variant by comparing with previous runs."""
        # This is a simplified version - in a real implementation, you'd compare
        # configs more thoroughly to identify what makes this run unique
        for param_key, value in important_values.items():
            if 'variant' in param_key.lower() or 'experiment' in param_key.lower():
                return str(value).replace('_', '-')
        
        return None
    
    def _get_task_identifier(self, important_values: Dict[str, Any]) -> Optional[str]:
        """Extract task/dataset identifier."""
        task_keys = ['task', 'dataset', 'data']
        
        for key in task_keys:
            for param_key, value in important_values.items():
                if key in param_key.lower():
                    return str(value).replace('_', '-')
        
        return None
    
    def _clean_name(self, name: str) -> str:
        """Clean up the generated name."""
        # Remove special characters except hyphens and underscores
        name = re.sub(r'[^a-zA-Z0-9\-_\.]', '', name)
        
        # Replace multiple consecutive hyphens with single hyphen
        name = re.sub(r'-+', '-', name)
        
        # Remove leading/trailing hyphens
        name = name.strip('-')
        
        return name
    
    def _generate_fallback_name(self, target_run: Run) -> str:
        """Generate a fallback name when config analysis fails."""
        # Try to use run tags or job type
        if hasattr(target_run, 'tags') and target_run.tags:
            return f"run-{target_run.tags[0]}"
        
        if hasattr(target_run, 'job_type') and target_run.job_type:
            return f"run-{target_run.job_type}"
        
        # Use run ID as last resort
        return f"run-{target_run.id[:8]}"
    
    def update_run_name(self, run_id: str, new_name: str) -> bool:
        """Update the run name."""
        try:
            run = self._get_run(run_id)
            if not run:
                return False
            
            run.name = new_name
            run.save()
            return True
        except Exception as e:
            if self.verbose:
                click.echo(f"Error updating run name: {e}")
            return False 