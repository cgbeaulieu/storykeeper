# Storykeeper

A local, private research assistant for your manuscript and worldbuilding notes.

Point Storykeeper at your files (characters, history, culture, plot, locations)
and ask questions in plain English. It answers from your own material and cites
the file each answer came from.

Everything runs on your own computer. Your writing is never uploaded, never sent
to an AI company, and never used to train anything. After the one-time setup
downloads, it works with your internet connection turned off.

## Features

- **Finds forgotten details.** Ask for everything you've written about the
  northern houses, and it will include the paragraph in a location note from
  eight months ago.
- **Answers questions from your notes.** "What colour are Maren's eyes?", "How
  does the guild's succession work?", "Where did I establish the winter
  crossing?"
- **Separates the manuscript from the plan.** Passages from your manuscript and
  passages from your outline are labelled differently, and the answer tells you
  which is which. If they contradict each other, it says so.
- **Cites its sources.** Every answer cites the file and section it came from,
  and you can view the raw passages it was built from.
- **Fast updates.** After a writing session, re-indexing takes seconds, because
  only the files you changed are re-read.
- **Exact text search.** One command finds every place a phrase appears, with no
  AI involved.

## Limitations

**It is not an exhaustive continuity checker.** For each question, Storykeeper
searches your material and reads back the handful of most relevant passages. It
does not read your whole manuscript every time. "Everything I've said about the
timeline" works well; "find every contradiction in my timeline" will find some
contradictions, not all of them. Do not rely on it to tell you that something is
*not* in your writing.

**It does not write for you.** It answers questions about what you've written.
It is not a drafting assistant and is not set up to imitate your voice.

**Answer quality depends on your computer.** The AI runs on your own hardware,
so a machine with a good graphics card gives noticeably better answers than one
without. Retrieval works well on any machine, and there is a mode that skips the
AI entirely.

## Requirements

| | |
|---|---|
| **Disk space** | About 6 GB, mostly the AI model |
| **Memory** | 16 GB RAM recommended; 8 GB works with a smaller model |
| **Python** | Version 3.11 or newer, free |
| **Ollama** | Free. Runs the AI model locally |
| **Internet** | Only during setup |

## Installation

### 1. Install Python

Download and install the latest version from <https://www.python.org/downloads/>.

> **Windows:** on the first screen of the installer, tick the checkbox
> **"Add python.exe to PATH"** before clicking Install. If you miss it, nothing
> else will work, and the fix is to run the installer again and tick it.

A Mac may already have Python. Installing the current version anyway does no
harm.

### 2. Install Ollama

Download and install it from <https://ollama.com>. Ollama runs the AI model on
your own machine instead of on someone else's server.

Then open a terminal:

- **Windows:** press Start, type `cmd`, press Enter
- **Mac:** press Cmd+Space, type `Terminal`, press Enter

and download the AI model:

```bash
ollama pull llama3.1:8b
```

The download is about 5 GB and takes a few minutes, but you only need to do it once. If your
computer has much more or much less than 16 GB of RAM, see
[Choosing a model](#choosing-a-model) first, as a different model may suit it
better.

Leave Ollama running. On Windows and Mac it starts with your computer and sits
in the system tray or menu bar.

### 3. Download Storykeeper

```bash
git clone https://github.com/cgbeaulieu/storykeeper.git
```

Or download the ZIP from that page and extract it somewhere you'll remember.
Either way you end up with a folder called `storykeeper`.

### 4. Run the setup script

Open that folder and run the setup script for your system:

- **Windows:** double-click `setup.cmd`
- **Mac / Linux:** open a terminal in that folder and run `./setup.sh`

It creates a private Python environment inside the folder and installs the four
packages Storykeeper needs. It doesn't change anything else on your computer and
doesn't touch your writing. It takes a minute or two and needs the internet.

**On Windows**, then double-click `finish-setup.cmd`. It downloads the AI model
named in your settings (if you haven't already) and checks that every part is
working.

> **Windows shortcut:** after setup you don't need a terminal at all.
> Double-click `index-my-writing.cmd` to index your writing and
> `ask-storykeeper.cmd` to start asking questions. The commands below do the
> same things, plus a few more.

## Usage

Open a terminal in the Storykeeper folder.

On **Windows**, type `.\storykeeper`, including the `.\` at the front, which
tells Windows to look in the current folder. On **Mac and Linux**, type
`./storykeeper.sh` instead. The examples below use the Windows form.

### Add your writing

Put your files in the `library` folder, sorted into these subfolders:

```
library/
  manuscript/     the book itself: chapters, drafts, scenes
  characters/     character sheets, backstories, voice notes
  history/        timelines, past events, backstory of the world
  culture/        religion, language, customs, politics, factions
  locations/      places, maps, geography, buildings
  plot/           outlines, beat sheets, structure notes, what-ifs
  other/          anything that doesn't fit above
```

The folder a file is in tells Storykeeper what kind of material it is. A
question about someone's appearance checks your character notes first; a
question about what happens in chapter twelve checks the manuscript.

Subfolders inside these are fine, and you don't have to use every folder. If
your files are already organised differently, you can keep your own folder
names and list them under `doc_type_folders` in `storykeeper.local.toml`. If
you're unsure where something goes, put it in `other/`. It is still fully
searchable.

**Supported formats:** `.txt`, `.md`, `.docx` (Word), `.rtf` and `.rtfd`
(TextEdit), `.odt`, `.pdf`, and Scrivener projects (`.scriv`). Scanned PDFs,
which are images of pages rather than text, can't be read. To check, try
selecting a sentence in the PDF with your mouse.

### Index your writing

```bash
.\storykeeper index
```

The first run takes a minute or two and downloads a small search model (about
130 MB). After that, each run takes seconds, because only changed files are
re-read.

Run it again after each writing session. `status` will tell you if you forget.

### Ask a question

```bash
.\storykeeper ask "what colour are Maren's eyes?"
```

The answer includes numbered citations and a list of the files they came from.
To see the passages the answer was built from, add `-s`:

```bash
.\storykeeper ask -s "how does the guild choose its next master?"
```

Use `-s` when the answer matters, so you can check the passages yourself.

To skip the AI and just see the most relevant passages (much faster, and useful
on a slower computer):

```bash
.\storykeeper ask --no-llm "the winter crossing"
```

Other options for `ask` and `chat`:

| | |
|---|---|
| `-k 15` | retrieve more passages (default 8) |
| `--type character` | only search one kind of material |
| `--model <name>` | use a different Ollama model for this run only |

### Chat

```bash
.\storykeeper chat
```

Chat keeps the conversation going, so you can ask follow-up questions:

```
> Who is Kestrel?
  ...
> What colour is her hair?
  ...
```

Commands inside chat:

| | |
|---|---|
| `/sources` | show or hide the passages behind each answer |
| `/k 12` | retrieve more passages per question (default 8) |
| `/type character` | only search one kind of material |
| `/type all` | search everything again |
| `/new` | clear the conversation |
| `/quit` or `exit` | leave chat |

### Find exact words

```bash
.\storykeeper find "Ninefold Court"
```

Lists every place those words appear, with the file and a line of context. No AI
is involved. It ignores capitals and curly-vs-straight quotes, so `don't` finds
`don’t`. Add `--files` to list only the matching files.

### Check status

```bash
.\storykeeper status
```

Shows how much is indexed, when it was last updated, whether any files have
changed since, and whether Ollama is running.

## Choosing a model

The default model, `llama3.1:8b`, suits a typical computer with 16 GB of RAM. If
yours is different, pick a model from the table below and download it with
`ollama pull <name>`. Then create a plain text file called
`storykeeper.local.toml` in the Storykeeper folder containing:

```toml
[llm]
model = "mistral-nemo:12b"
```

using your chosen model's name. Settings in this file override the shipped
`storykeeper.toml`, and keeping them separate means updating Storykeeper never
overwrites your choice. On Windows, `finish-setup.cmd` downloads whichever model
this file names.

| Your computer | Model | What to expect |
|---|---|---|
| 8 GB RAM, no graphics card | `llama3.2:3b` | Fast. Finds well, summarises poorly |
| 16 GB RAM, no graphics card | `llama3.1:8b` | The default. Good for lookups, fairly slow |
| 8–12 GB of video memory | `mistral-nemo:12b` | Noticeably better reasoning |
| 16–24 GB of video memory | `qwen2.5:32b` | Strong reasoning and summaries |

Macs with Apple Silicon (M1 and later) share memory between the processor and
graphics, so a 16 GB M-series Mac can use the 8–12 GB video memory row.

Model names change over time. If one of these no longer exists, look at
<https://ollama.com/library> for a current equivalent with a long context
window.

If you're unsure, run `.\storykeeper ask --no-llm "anything"` first. If the
passages it finds are good, retrieval is working, and the model only affects how
the answer is written.

## Troubleshooting

**"Ollama is not running"**
Open the Ollama app; on Windows and Mac it is in the system tray or menu bar. Or
run `ollama serve` in a terminal and leave that window open.

**"The AI model ... is not installed"**
Run the `ollama pull` command shown in the message. It is a large download and
only needed once.

**"Nothing has been indexed yet"**
Put files in `library/` and run `.\storykeeper index`.

**Windows says `storykeeper` is not recognised**
Type `.\storykeeper`, with the dot and backslash at the front, and check that
your terminal is in the Storykeeper folder.

**The answer is vague, or misses something you know you wrote**
Try these in order:

1. Run `.\storykeeper find "the exact words"` to confirm the text is indexed. If
   `find` doesn't see it, `index` hasn't read that file yet.
2. Ask again with `-s` and read the passages. If the right passage is there but
   the answer is poor, try a bigger model.
3. Retrieve more passages: `.\storykeeper ask -k 15 "..."`.

**It mixes up two characters**
This is usually caused by formatting. Storykeeper splits your notes on headings and blank
lines. Putting each character under their own heading (`# Maren Vesh`) keeps
them separate.

**Answers are very slow**
This is normal without a graphics card. Use a smaller model, or use `--no-llm`,
which skips the AI and is instant.

**"Reading PDFs needs one extra piece"**
The PDF reader wasn't installed, usually because Storykeeper was set up with an
older version. Run the setup script again. It is safe and won't touch your
writing.

**"No text could be pulled out of this PDF"**
The PDF is a scan (images of pages, not text). Storykeeper can't read those.

**Google Docs, Apple Pages, old `.doc` files, OneNote**
Storykeeper tells you what to do when it finds one. In short: export or save a
copy as `.docx` and put that in `library/`. Google Docs has no file on your
computer to read; the writing is on Google's servers, and Storykeeper does not
connect to outside services.

**Something else went wrong**
Rebuilding the index is always safe and never touches your writing:

```bash
.\storykeeper index --rebuild
```

## Privacy and storage

- Your files stay in `library/`. Storykeeper reads them and never writes to them.
- The search index is stored in `index/`: passages of your text, plus a list of
  numbers for each passage. It is also only on your computer.
- Both folders are excluded from Git, so they can't be uploaded by accident even
  if this folder is in a Git repository.
- The AI model runs inside Ollama on `localhost`, which means your own machine.
- There are two downloads during setup and none afterwards: the search model
  (~130 MB) and the AI model (~5 GB). After the first successful run,
  Storykeeper puts the search library into offline mode so it doesn't check for
  updates either.

You can confirm this by disconnecting from the internet and using it normally.

## Settings and development

- `storykeeper.toml` contains every setting, each with a comment explaining it.
  To keep your own changes separate, copy it to `storykeeper.local.toml` and
  edit that. It overrides the original setting by setting.
- `SPEC.md` explains how Storykeeper works and why it was designed this way.
- Run the tests with `.venv\Scripts\python -m unittest discover -s tests`
  (or `.venv/bin/python -m unittest discover -s tests` on Mac and Linux).

## Contributing

Issues and pull requests are welcome, with one firm rule: **nothing may leave the
user's machine while indexing or answering.** A change that adds a network call,
a hosted service, or a dependency with telemetry on by default won't be merged,
even if it improves the answers. `CLAUDE.md` and `SPEC.md` have more detail,
including how new dependencies are vetted.

Never attach real manuscript material to an issue. Make up a small example that
shows the problem instead.

## License

[MIT](LICENSE).
