"""Runtime configuration, read from environment / .env at the project root."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_OFFLINE", "1")          # models are already on disk

# --- Claude on Vertex AI -------------------------------------------------------------
VERTEX_PROJECT_ID = os.getenv("VERTEX_PROJECT_ID", "")   # your GCP project with Claude enabled on Vertex AI
VERTEX_REGION = os.getenv("VERTEX_REGION", "global")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "600"))
MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "5"))

# USD per million tokens (Sonnet list price; override for other models / negotiated rates)
PRICE_IN = float(os.getenv("PRICE_INPUT_PER_MTOK", "3.0"))
PRICE_OUT = float(os.getenv("PRICE_OUTPUT_PER_MTOK", "15.0"))

# --- System One (Laya) ---------------------------------------------------------------
LAYA_MODEL_PATH = os.getenv("LAYA_MODEL_PATH", str(PROJECT_ROOT / "models" / "laya"))
EMBED_MODEL_PATH = os.getenv("EMBED_MODEL_PATH", str(PROJECT_ROOT / "models" / "bge-small-en-v1.5"))
LAYA_DEVICE = os.getenv("LAYA_DEVICE") or None        # None -> auto (MPS on Apple Silicon)
DEFAULT_TOP_K = int(os.getenv("SYSTEM_ONE_TOP_K", "6"))
DEFAULT_STRATEGY = os.getenv("SYSTEM_ONE_STRATEGY", "hybrid")
DIRECT_ANSWER_THRESHOLD = float(os.getenv("DIRECT_ANSWER_THRESHOLD", "0.70"))
