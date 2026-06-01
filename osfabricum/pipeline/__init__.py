"""Build Pipeline (M18) — end-to-end plan→rootfs→image coordinator."""

from osfabricum.pipeline.coordinator import PipelineResult, PipelineSpec, run_pipeline

__all__ = ["PipelineResult", "PipelineSpec", "run_pipeline"]
