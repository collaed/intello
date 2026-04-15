"""Data models for the AI Router."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Tier(Enum):
    FREE = "free"
    PAID = "paid"


class TaskType(Enum):
    CODE = "code"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    MATH = "math"
    GENERAL = "general"
    VISION = "vision"
    LONG_CONTEXT = "long_context"


@dataclass
class LLMProvider:
    name: str
    model_id: str
    provider: str  # openai, anthropic, google, groq, mistral, etc.
    tier: Tier
    context_window: int
    strengths: list[TaskType] = field(default_factory=list)
    cost_per_1k_input: float = 0.0   # USD
    cost_per_1k_output: float = 0.0  # USD
    env_key: str = ""                 # env var name for API key
    api_key: Optional[str] = None
    available: bool = False
    daily_limit: int = 0             # 0 = unlimited
    notes: str = ""


@dataclass
class RoutingPlan:
    prompt: str
    task_type: TaskType
    estimated_tokens: int
    primary: Optional[LLMProvider] = None
    fallbacks: list[LLMProvider] = field(default_factory=list)
    degraded: bool = False
    missing_keys: list[str] = field(default_factory=list)
    estimated_cost: float = 0.0
    reasoning: str = ""


@dataclass
class LLMResponse:
    provider_name: str
    model_id: str
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    degraded: bool = False
