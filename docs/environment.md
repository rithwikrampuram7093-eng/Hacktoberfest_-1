# Development environment inspection

Recorded on **28 October 2026**, using the user's India time context. This is an
inspection record, not a live health report. Recheck `/api/health` for the current
runtime state.

| Component | Observed state |
| --- | --- |
| Workspace | `C:\Users\Admin\Downloads\HCK` |
| Python | Existing Python 3.12 at `C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe`, outside the session's `PATH` |
| Backend environment | Repository `.venv` created using that installation; backend dependencies installed successfully |
| Ollama executable | Existing `C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe`, outside the session's `PATH` |
| Ollama HTTP API | `http://127.0.0.1:11434/api/tags` reachable; returned `models: []` |
| Local Gemma runtime | No model was available in the inspected Ollama inventory |
| Docker | Docker CLI/runtime absent in the inspected environment |
| Sample execution | Not run on the host; no Docker baseline or repaired sample run verified |

Existing Python and Ollama installations were reused. Neither tool was
reinstalled, and no model download was started. A model made available only
inside Claude Code or another assistant is not evidence of a local Ollama model.

The setup script first reuses the repository virtual environment. If a new one
is needed, it checks `python.exe`/`py.exe`, then common per-user Python directories
under `%LOCALAPPDATA%\Programs\Python`. `-PythonPath` selects an existing
installation explicitly. The script does not install a Python runtime.

To enable the real end-to-end demonstration, the operator still needs Docker
Desktop with a reachable Linux-container daemon, the built
`rootcause-runner:local` image, and a downloaded local model. A suggested model
tag is [`gemma3:4b` from Ollama](https://ollama.com/library/gemma3%3A4b):

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull gemma3:4b
```

Set `RC_OLLAMA_MODEL=gemma3:4b` in `.env` after download, or leave the variable
empty for installed Gemma auto-detection. This command is documentation for the
operator; it was not executed during development. See [the README](../README.md)
for runner-image build and service startup commands.
