# Castellan Plugin
Locksmith plugin intended for managing Weirwood server credentials

## Setup
Copy the `src/castellan` dir from this repo into the `src/locksmith/plugins` dir in the locksmith repo.

Add the following line to the `[project.entry-points."locksmith.plugins"]` section in `pyproject.toml` in the locksmith 
repo. In its current state, this plugin will not function without the healthKERI plugin shown below.

```toml
[project.entry-points."locksmith.plugins"]
healthkeri = "locksmith.ui.vault.healthKERI.plugin:HealthKERIPlugin"
whisper = "locksmith.plugins.whisper.plugin:WhisperPlugin"
```

Copy the files from `assets/material-icons` in the Whisper repo into `assets/material-icons` in the locksmith repo.

from the locksmith repo venv, run `pip install -e .`, then follow instructions in the locksmith repo README to update
assets.
