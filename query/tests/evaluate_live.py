"""Run the authenticated integrated acceptance suite from the parent project."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "merged_acceptance.py"), run_name="__main__")
