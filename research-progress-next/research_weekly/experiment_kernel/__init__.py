"""Load the common scientific protocols from the source tree or the deployed package."""
from pathlib import Path

source = Path(__file__).resolve().parents[3] / "research-data-center-next" / "tools"
if not (Path(__file__).parent / "research_experiment.py").is_file() and source.is_dir():
    __path__.append(str(source))
