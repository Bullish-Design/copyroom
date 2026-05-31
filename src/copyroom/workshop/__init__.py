"""Workshop operations — scenario rendering, golden testing, update simulation."""

from .golden import golden_diff as golden_diff
from .golden import refresh_golden as refresh_golden
from .model import (
    GoldenDiff as GoldenDiff,
    GoldenDiffResult as GoldenDiffResult,
    GoldenStatus as GoldenStatus,
    RenderStatus as RenderStatus,
    ScenarioRender as ScenarioRender,
    SimStatus as SimStatus,
    UpdateSimulation as UpdateSimulation,
    UpdateSimulationResult as UpdateSimulationResult,
)
from .render import render_scenario as render_scenario
from .simulate import run_update_simulation as run_update_simulation
