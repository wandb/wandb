"""AI-powered run name generator for W&B runs using LLM analysis."""

import json
import os
import re
from typing import Any, Dict, List, Optional

import click

from wandb.apis.public import Api, Run

# OpenAI integration
try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class RunNameGenerator:
    """Generate meaningful run names using AI analysis of W&B run configurations."""
    
    def __init__(
        self,
        api: Any,
        entity: str,
        project: str,
        max_name_length: int = 50,
        verbose: bool = False,
        openai_model: str = "gpt-4o-mini",
        prompt_file: Optional[str] = None,
        config_limit: int = 50,
        include_previous_configs: bool = True
    ):
        """Initialize the AI-powered run name generator.
        
        Args:
            api: W&B API client
            entity: Entity name
            project: Project name
            max_name_length: Maximum length of generated names
            verbose: Whether to show detailed analysis
            openai_model: OpenAI model to use for analysis
            prompt_file: Path to custom prompt file (optional)
            config_limit: Maximum number of config parameters to include
            include_previous_configs: Whether to include previous run configs as context
        """
        self.api = api
        self.entity = entity
        self.project = project
        self.max_name_length = max_name_length
        self.verbose = verbose
        self.config_limit = config_limit
        self.include_previous_configs = include_previous_configs
        
        # Initialize public API for run data access
        self.public_api = Api()
        
        # LLM configuration - required for this AI-powered approach
        if not HAS_OPENAI:
            raise ImportError("OpenAI package is required. Install with: pip install openai")
        
        self.openai_model = openai_model
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable")
        
        self.openai_client = openai.OpenAI(api_key=api_key)
        
        # Load prompt template
        self.system_prompt = self._load_prompt_template(prompt_file)
        
        if self.verbose:
            click.echo(f"✅ AI-powered name generation enabled with {openai_model}")
    
    def _load_prompt_template(self, prompt_file: Optional[str] = None) -> str:
        """Load prompt template from file or use default."""
        if prompt_file and os.path.exists(prompt_file):
            try:
                with open(prompt_file, 'r') as f:
                    return f.read().strip()
            except Exception as e:
                if self.verbose:
                    click.echo(f"Warning: Could not load prompt file {prompt_file}: {e}")
                    click.echo("Using default prompt")
        
        # Try to load default prompt file from the same directory
        default_prompt_path = os.path.join(os.path.dirname(__file__), 'default_prompt.txt')
        if os.path.exists(default_prompt_path):
            try:
                with open(default_prompt_path, 'r') as f:
                    return f.read().strip()
            except Exception as e:
                if self.verbose:
                    click.echo(f"Warning: Could not load default prompt file: {e}")
        
        # Fallback to hardcoded prompt
        return """You are an expert ML engineer analyzing experiment configurations to generate concise, meaningful run names.

TASK: Generate a short, descriptive name (max 40 chars) that captures the essence of this ML experiment.

GUIDELINES:
1. Analyze the FULL configuration to understand the experiment
2. Identify the most distinguishing and important aspects
3. Use standard ML abbreviations (lr=learning_rate, bs=batch_size, etc.)
4. Make it human-readable and informative
5. Consider the context of previous runs to avoid redundancy
6. Focus on what makes this run unique or interesting

EXAMPLES:
- bert-large-lr2e-5-bs16-squad (NLP fine-tuning)
- resnet50-lr0.01-bs64-cifar10 (Computer Vision)
- gpt2-ppo-lr3e-6-kl0.05-tldr (RL training)
- vit-base-lr1e-4-bs32-imagenet (Vision Transformer)

Generate ONLY the run name, no explanation."""
    
    def generate_name(self, run_id: str, previous_runs_count: int = 3) -> str:
        """Generate a meaningful name for the run using AI analysis.
        
        Args:
            run_id: The run ID to generate a name for
            previous_runs_count: Number of previous runs to analyze for context
            
        Returns:
            AI-generated run name
        """
        # Get the target run
        target_run = self._get_run(run_id)
        if not target_run:
            raise ValueError(f"Run {run_id} not found")
            
        if self.verbose:
            click.echo(f"Analyzing run: {target_run.name}")
            click.echo(f"Created: {target_run.created_at}")
        
        # Get full config (let AI decide what's important)
        config = target_run.config
        if not config:
            raise ValueError(f"Run {run_id} has no configuration data")
            
        if self.verbose:
            click.echo(f"Config has {len(config)} parameters")
        
        # Get previous runs with their configs for context
        previous_runs = []
        if previous_runs_count > 0 and self.include_previous_configs:
            previous_runs = self._get_previous_runs(target_run, previous_runs_count)
            if self.verbose:
                click.echo(f"Using {len(previous_runs)} previous runs for context")
        
        # Generate name using pure AI analysis
        generated_name = self._generate_name_with_ai(config, target_run, previous_runs)
        
        if self.verbose:
            click.echo(f"🤖 AI generated name: {generated_name}")
        
        return self._ensure_name_length(generated_name)
    
    def _generate_name_with_ai(self, config: Dict[str, Any], target_run: Run, previous_runs: List[Run]) -> str:
        """Generate a name using pure AI analysis - no heuristics."""
        
        # Create the AI prompt with full context
        prompt = self._create_ai_prompt(config, target_run, previous_runs)
        
        try:
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
                temperature=0.1
            )
            
            generated_name = response.choices[0].message.content.strip()
            
            # Clean and validate the generated name
            clean_name = self._clean_name(generated_name)
            
            if not clean_name or len(clean_name) < 3:
                raise ValueError("AI generated invalid or too short name")
            
            return clean_name
            
        except Exception as e:
            if self.verbose:
                click.echo(f"AI generation error: {e}")
            raise RuntimeError(f"Failed to generate name with AI: {e}")
    
    def _create_ai_prompt(self, config: Dict[str, Any], target_run: Run, previous_runs: List[Run]) -> str:
        """Create a comprehensive prompt for AI analysis."""
        
        prompt_parts = []
        
        # Basic run info
        prompt_parts.append("CURRENT RUN:")
        prompt_parts.append(f"Name: {target_run.name}")
        prompt_parts.append(f"Created: {target_run.created_at}")
        prompt_parts.append(f"State: {target_run.state}")
        
        # Full configuration (truncated if too large)
        config_str = self._format_config_for_prompt(config)
        prompt_parts.append(f"\nCONFIGURATION:")
        prompt_parts.append(config_str)
        
        # Previous runs context with their configs
        if previous_runs:
            prompt_parts.append(f"\nPREVIOUS RUNS (for context):")
            for i, run in enumerate(previous_runs[:3]):  # Limit to 3 for token efficiency
                prompt_parts.append(f"{i+1}. {run.name} ({run.created_at})")
                if run.config:
                    prev_config_str = self._format_config_for_prompt(run.config, max_items=10)
                    prompt_parts.append(f"   Config: {prev_config_str}")
        
        prompt_parts.append(f"\nGenerate a concise, descriptive run name (max 40 chars):")
        
        return "\n".join(prompt_parts)
    
    def _format_config_for_prompt(self, config: Dict[str, Any], max_items: Optional[int] = None) -> str:
        """Format configuration for inclusion in prompt."""
        if not config:
            return "No configuration"
        
        # Flatten nested configs
        flat_config = self._flatten_config(config)
        
        # Apply limits if specified
        if max_items:
            items = list(flat_config.items())[:max_items]
            if len(flat_config) > max_items:
                flat_config = dict(items)
                flat_config['...'] = f"({len(config) - max_items} more parameters)"
        
        # Apply overall limit for token efficiency
        if len(flat_config) > self.config_limit:
            items = list(flat_config.items())[:self.config_limit]
            flat_config = dict(items)
            flat_config['...'] = f"({len(config) - self.config_limit} more parameters)"
        
        # Format as readable string
        config_lines = []
        for key, value in flat_config.items():
            # Truncate very long values
            if isinstance(value, str) and len(value) > 100:
                value = value[:100] + "..."
            config_lines.append(f"  {key}: {value}")
        
        return "\n".join(config_lines)
    
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
    
    def _clean_name(self, name: str) -> str:
        """Clean up the generated name."""
        # Remove quotes and clean up
        name = name.strip('"\'')
        
        # Remove special characters except hyphens, underscores, and dots
        name = re.sub(r'[^a-zA-Z0-9\-_\.]', '', name)
        
        # Replace multiple consecutive hyphens with single hyphen
        name = re.sub(r'-+', '-', name)
        
        # Remove leading/trailing hyphens
        name = name.strip('-')
        
        return name
    
    def _ensure_name_length(self, name: str) -> str:
        """Ensure name doesn't exceed max length."""
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
        """Get previous runs with their configs for context analysis."""
        try:
            # Filter for runs created before the target run
            target_created_at = target_run.created_at
            runs = self.public_api.runs(
                f"{self.entity}/{self.project}",
                filters={"createdAt": {"$lt": target_created_at}},
                order="-created_at"
            )
            if self.verbose:
                click.echo(f"Found runs created before {target_created_at}")
            
            previous_runs = []
            for run in runs:
                if len(previous_runs) < count:
                    previous_runs.append(run)
                if len(previous_runs) >= count:
                    break
            
            if self.verbose:
                click.echo(f"Previous runs: {[f'{run.name} ({run.created_at})' for run in previous_runs]}")
            return previous_runs
        except Exception as e:
            if self.verbose:
                click.echo(f"Error fetching previous runs: {e}")
            return []
    
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