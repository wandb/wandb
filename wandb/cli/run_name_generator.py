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
        openai_model: str = "gpt-4o-mini"
    ):
        """Initialize the AI-powered run name generator.
        
        Args:
            api: W&B API client
            entity: Entity name
            project: Project name
            max_name_length: Maximum length of generated names
            verbose: Whether to show detailed analysis
            openai_model: OpenAI model to use for analysis
        """
        self.api = api
        self.entity = entity
        self.project = project
        self.max_name_length = max_name_length
        self.verbose = verbose
        
        # Initialize public API for run data access
        self.public_api = Api()
        
        # LLM configuration - required for this AI-powered approach
        if not HAS_OPENAI:
            # TODO: make openai dependency optional
            raise ImportError("OpenAI package is required. Install with: pip install openai")
        
        self.openai_model = openai_model
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY environment variable")
        
        self.openai_client = openai.OpenAI(api_key=api_key)
        if self.verbose:
            click.echo(f"✅ AI-powered name generation enabled with {openai_model}")

        # Important parameter categories for config analysis
        self.important_params = {
            # Model architecture
            'model', 'model_name', 'model_type', 'architecture', 'arch', '_name_or_path',
            # Training hyperparameters
            'learning_rate', 'lr', 'batch_size', 'epochs', 'epoch', 'num_train_epochs',
            'optimizer', 'weight_decay', 'momentum', 'temperature',
            # Model configuration
            'hidden_size', 'num_layers', 'num_heads', 'vocab_size', 'seq_length',
            # Task and data
            'dataset', 'data', 'task', 'task_name', 'experiment', 'exp_name',
            # RL-specific
            'kl_coef', 'cliprange', 'num_ppo_epochs', 'total_episodes', 'algorithm', 
            'environment', 'gamma', 'lam', 'vf_coef',
            # Domain-specific
            'loss', 'loss_function', 'activation', 'dropout', 'variant'
        }
    
    def generate_name(self, run_id: str, previous_runs_count: int = 5) -> str:
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
            click.echo(f"Current name: {target_run.name}")
        
        # Extract key parameters from config
        config = target_run.config
        if not config:
            raise ValueError(f"Run {run_id} has no configuration data")
            
        if self.verbose:
            click.echo(f"Config keys: {list(config.keys())}")
        
        # Get previous runs for context if requested
        previous_runs = []
        if previous_runs_count > 0:
            previous_runs = self._get_previous_runs(target_run, previous_runs_count)
            if self.verbose:
                click.echo(f"Analyzing {len(previous_runs)} previous runs for context")
        
        # Generate name using AI analysis
        generated_name = self._generate_name_with_ai(config, target_run, previous_runs)
        
        if self.verbose:
            click.echo(f"🤖 AI generated name: {generated_name}")
        
        return self._ensure_name_length(generated_name)
    
    def _generate_name_with_ai(self, config: Dict[str, Any], target_run: Run, previous_runs: List[Run]) -> str:
        """Generate a name using AI analysis of the configuration."""
        
        # Extract and analyze important parameters
        important_params = self._extract_important_params(config)
        
        # Create the AI prompt
        prompt = self._create_ai_prompt(important_params, target_run, previous_runs)
        
        try:
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert AI system specialized in analyzing machine learning experiments and generating concise, meaningful names for W&B runs. Your task is to create descriptive names that capture the essence of ML experiments.

RULES:
1. Keep names under 40 characters
2. Use hyphens to separate components  
3. Focus on the most distinguishing and important features
4. Use standard ML abbreviations (lr=learning_rate, bs=batch_size, ep=epochs, etc.)
5. Prioritize: model → key hyperparameters → domain/task → unique aspects
6. For RL: emphasize algorithm + key RL parameters (kl_coef, cliprange, etc.)
7. For NLP: emphasize model + task + key params
8. For CV: emphasize architecture + dataset + key params
9. Make names human-readable and informative
10. Avoid redundant or obvious information

EXAMPLES:
- bert-large-lr2e-5-bs16-squad (NLP fine-tuning)
- resnet50-lr0.01-bs64-cifar10 (Computer Vision)
- gpt2-ppo-lr3e-6-kl0.05-tldr (RL language model training)
- vit-base-lr1e-4-bs32-imagenet (Vision Transformer)
- pythia1b-rlhf-kl0.05-bs64 (RLHF training)"""
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                max_tokens=50,
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
    
    def _create_ai_prompt(self, important_params: Dict[str, Any], target_run: Run, previous_runs: List[Run]) -> str:
        """Create a comprehensive prompt for AI analysis."""
        
        prompt_parts = []
        
        # Basic run info
        prompt_parts.append("Analyze this ML experiment and generate a concise, descriptive run name:")
        prompt_parts.append(f"Current name: {target_run.name}")
        
        # Key parameters (prioritized and filtered)
        if important_params:
            prompt_parts.append("\nKey configuration parameters:")
            
            # Prioritize the most important parameters for naming
            priority_order = [
                # Model info (highest priority)
                ('model_type', 'model', 'model_name', '_name_or_path', 'architecture'),
                # Algorithm (for RL)
                ('num_ppo_epochs', 'algorithm'),
                # Key hyperparameters
                ('learning_rate', 'lr'),
                ('batch_size',),
                ('epochs', 'epoch', 'num_train_epochs'),
                # RL specific
                ('kl_coef', 'cliprange', 'gamma', 'temperature'),
                # Task/domain
                ('task', 'task_name', 'dataset', 'exp_name'),
                # Other important
                ('optimizer', 'hidden_size', 'vocab_size')
            ]
            
            shown_params = set()
            for priority_group in priority_order:
                for key in priority_group:
                    matching_params = [(k, v) for k, v in important_params.items() 
                                     if key in k.lower() and k not in shown_params]
                    for param_key, value in matching_params[:1]:  # Take first match from each group
                        prompt_parts.append(f"- {param_key}: {value}")
                        shown_params.add(param_key)
                        if len(shown_params) >= 12:  # Limit total parameters
                            break
                if len(shown_params) >= 12:
                    break
        
        # Context from previous runs
        if previous_runs:
            prompt_parts.append(f"\nRecent runs in this project:")
            for run in previous_runs[:3]:
                prompt_parts.append(f"- {run.name} ({run.state})")
        
        # Domain detection and hints
        domain_hints = self._detect_domain(important_params)
        if domain_hints:
            prompt_parts.append(f"\nDomain context: {domain_hints}")
        
        prompt_parts.append("\nGenerate a concise, descriptive run name (max 40 chars):")
        
        return "\n".join(prompt_parts)
    
    def _detect_domain(self, important_params: Dict[str, Any]) -> str:
        """Detect the ML domain from configuration parameters."""
        param_values = [str(v).lower() for v in important_params.values()]
        param_keys = [k.lower() for k in important_params.keys()]
        
        # RL detection
        rl_indicators = ['ppo', 'num_ppo_epochs', 'kl_coef', 'cliprange', 'reward', 'episode']
        if any(indicator in ' '.join(param_keys + param_values) for indicator in rl_indicators):
            return "Reinforcement Learning (RL) training"
        
        # NLP detection  
        nlp_indicators = ['bert', 'gpt', 'transformer', 'token', 'seq_length', 'vocab_size', 'attention']
        if any(indicator in ' '.join(param_values + param_keys) for indicator in nlp_indicators):
            return "Natural Language Processing (NLP)"
        
        # CV detection
        cv_indicators = ['resnet', 'vit', 'vision', 'image', 'cnn', 'conv', 'patch']
        if any(indicator in ' '.join(param_values + param_keys) for indicator in cv_indicators):
            return "Computer Vision (CV)"
        
        return "Machine Learning experiment"
    
    def _extract_important_params(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters that are important for naming."""
        important_values = {}
        
        # Flatten nested configs
        flat_config = self._flatten_config(config)
        
        # Extract parameters matching our important patterns
        for key, value in flat_config.items():
            key_lower = key.lower()
            
            # Check if this key matches any important parameter patterns
            for param in self.important_params:
                if param in key_lower:
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
        """Get previous runs for context analysis."""
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