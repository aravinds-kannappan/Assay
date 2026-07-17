"""Log adapters: normalize each harness's per-sample output into SampleRecord."""
from .lm_eval import load_lm_eval_samples

__all__ = ["load_lm_eval_samples"]
