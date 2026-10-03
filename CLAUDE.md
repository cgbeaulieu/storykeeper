# CLAUDE.md

## What this is

**Storykeeper** — a fully local, offline research assistant over a novelist's own
material. A writer can query their own manuscript, character sheets,
worldbuilding, history, culture and location notes, without any of it being
transmitted to an AI company.

`README.md` is the instructions for the writer. `SPEC.md` is the design, the
reasoning behind it, and what is still open. This file is for whoever — or
whatever — is working in the repo.

## The one rule that overrides everything

**Nothing may leave the user's machine at query time.**

That is the whole reason this project exists. Any dependency, service or design
that makes a network call while indexing or answering is disqualified, regardless
of how much better it would perform. One-time downloads during setup — the
embedding model and the Ollama model — are fine.

Concretely: no hosted LLM APIs, no cloud vector databases, no tracing or
analytics services, no libraries with telemetry on by default. If a package is
convenient but chatty, write the forty lines by hand instead. When adding any
dependency, check its telemetry behaviour and record the finding in `SPEC.md` —
there is a table there already.

---

# Setting this up on a writer's computer

**If you have been asked to install Storykeeper, this section is your brief.**
The person you are helping is a writer, probably not a developer, and has asked
for help so they don't have to do this by hand. Work through it and hand them
back something that runs.

Talk to them in plain language throughout. No jargon, no tracebacks, and no
assumption that they know what a virtual environment or a context window is.

### 1. Install the two prerequisites

- **Python 3.11 or newer** — <https://www.python.org/downloads/>.
  On Windows the installer's first screen has an **"Add python.exe to PATH"**
  checkbox. It must be ticked. Nothing works otherwise, and the only fix is to
  run the installer again.
- **Ollama** — <https://ollama.com>. This is what runs the AI locally.

### 2. Run the setup script

From the repository folder:

- Windows: `setup.cmd`
- Mac / Linux: `./setup.sh`

It creates a private Python environment in `.venv`, installs the four
dependencies, and creates the `library/` subfolders. It touches nothing else on
the machine.

### 3. Look at their hardware and choose the model — do not skip this

**This is the most useful thing you can do here, because it is the one decision
that could not be made in advance.** The default in `storykeeper.toml` is a guess
at a typical machine. Replace it with a real choice based on what they actually
have.

Check memory and graphics:

```
Windows      (Get-CIMInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
             Get-CIMInstance Win32_VideoController | Select-Object Name, AdapterRAM
Mac          system_profiler SPHardwareDataType | grep -E "Memory|Chip"
Linux        free -g ; nvidia-smi
```

Then pick from this table:

| What they have | Model | Notes |
|---|---|---|
| 8 GB RAM, no graphics card | `llama3.2:3b` | Retrieves well, summarises poorly |
| 16 GB RAM, no graphics card | `llama3.1:8b` | The shipped default |
| 8–12 GB VRAM | `mistral-nemo:12b` | Noticeably better reasoning |
| 16–24 GB VRAM | `qwen2.5:32b` | Genuinely good |

Put the choice in a new `storykeeper.local.toml` next to `storykeeper.toml`,
rather than editing the shipped file — it is gitignored, so updating Storykeeper
later never conflicts with it:

```toml
[llm]
model   = "mistral-nemo:12b"
num_ctx = 8192
```

Then download the model: `ollama pull <name>` — or, on Windows, run
`finish-setup.cmd`, which pulls whatever model the config names and then runs
`status`.

Two things that are easy to get wrong:

- **Apple Silicon uses unified memory.** A 16 GB M-series Mac comfortably runs a
  12–14B model — treat it as the VRAM row, not the RAM row.
- **Raise `num_ctx` if the hardware allows it.** It ships at 8192. More context
  means more of their own writing visible per answer, and it is the single
  setting with the biggest effect on answer quality. It costs memory, so scale
  it to the machine rather than maximising it blindly.

Say what you chose and why in your handover.

### 4. Check it works

```
storykeeper status
```

That reports whether Ollama is running, whether the chosen model is installed,
and what is indexed. Fix anything it flags before handing over. If you want to
watch the whole pipeline run before they have added any files of their own, make
two or three throwaway text files in `library/` and index those, then delete them
and run `storykeeper index` again to clear them out.

### 5. Hand it back

Tell them, in this order:

1. Put your writing in `library/`, in the subfolders that are there — see
   `library/README.md` for what goes where.
2. Run `storykeeper index`.
3. Run `storykeeper chat`.

On Windows the command is `.\storykeeper` — with the `.\` — because a bare
`storykeeper` collides with the folder of the same name. Windows users can also
just double-click `index-my-writing.cmd` and `ask-storykeeper.cmd` instead. On
Mac and Linux it is `./storykeeper.sh`.

### What not to do

- **Don't reorganise anything they already have.** If their folders are named
  differently from the suggested ones, add their names to `doc_type_folders` in
  `storykeeper.local.toml`. That is a one-line change and far better than asking
  a writer to restructure their files around a tool.
- **Don't commit anything.** `library/` and `index/` are gitignored for a
  reason — see below.
- **Don't install anything globally.** Everything goes in `.venv`.
- **Don't swap the components out.** The stack is deliberately small and
  deliberately offline. See the rule at the top.

---

# Working on the code

## Never commit anyone's material

`library/` and `index/` are gitignored and must stay that way. A single
accidental commit of an unpublished manuscript would defeat the entire purpose of
the project — and this repository is public.

Before any commit, verify nothing from `library/` or `index/` is staged. If
sample files are needed for development, keep them in `library/`, where they are
already ignored — never move them somewhere tracked for convenience. Test
fixtures are generated in temporary folders by the tests themselves.

## Working style

- Plain Python, short dependency list, no framework. LangChain and LlamaIndex are
  both larger, more fragile and more network-happy than this project needs.
- Prefer the standard library when the gap is small — a `.docx` is a zip of XML
  and is read here without `python-docx`.
- Cross-platform. Developed on Windows, used on Windows, Mac and Linux. No
  hardcoded path separators, no PowerShell-only assumptions inside the package.
- Every error message is for the writer. Each failure should say what to do
  next, in plain words. `storykeeper/errors.py` is the only exception type raised
  on purpose, and the CLI prints it without a traceback.
- Tests are stdlib `unittest`, so checking the tool needs nothing the tool does
  not already need:

  ```
  python -m unittest discover -s tests
  ```

## Test against what writers actually ask

Real use cases go in `SPEC.md`, under "Acceptance questions". They are the
acceptance test — add new ones there as they arrive, in the writer's own words.
Retrieval quality claims mean nothing until they are checked against the
questions people actually want answered.

Be honest in the README about what this cannot do. It is strong at recall and
weak at exhaustive audit. Overpromising there is how the tool loses a writer's
trust in week two.
