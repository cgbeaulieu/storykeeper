# Storykeeper

A private research assistant for your own book.

Point it at your manuscript and your notes — characters, history, culture, plot,
locations — and ask questions in plain English. It answers from your own
material and tells you which file every answer came from.

**Everything runs on your computer.** Your writing is never uploaded, never sent
to an AI company, and never used to train anything. After the one-time setup
downloads, you can turn off your internet connection entirely and it still
works.

---

## What it does

- **Finds things you forgot you wrote.** "Everything I've said about the
  northern houses" — including the paragraph buried in a location note from
  eight months ago.
- **Answers questions from your notes.** "What colour are Maren's eyes?" "How
  does the guild's succession work?" "Where did I establish the winter
  crossing?"
- **Knows the difference between the book and the plan.** A passage from your
  manuscript and a passage from your outline are labelled differently, and the
  answer will tell you which is which. If they contradict each other, it says so.
- **Shows its work.** Every answer cites the file and section it came from, and
  you can always see the raw passages behind it.
- **Keeps up with you.** After a writing session, updating the index takes
  seconds — it only re-reads the files you actually changed.
- **Searches literally too.** "Find every time I wrote *Ninefold Court*" is one
  command, with no AI involved at all.

## What it does not do

Worth saying up front, because the difference matters and nobody else will tell
you.

**It finds; it does not audit.** When you ask a question, it searches your
material and reads back the handful of most relevant passages. It does *not*
read all 200,000 words every time. So "everything I've said about the timeline"
works well, and "find every contradiction in my timeline" does not — it will
find some, never all. Exhaustive continuity checking is a different kind of tool
and this is not it. Do not trust it to tell you that something *isn't* there.

**It does not write for you.** It answers questions about what you've written.
It is not a drafting assistant and has not been set up to imitate your voice.

**Answer quality depends on your computer.** The AI runs on your own hardware,
which is the price of privacy — a machine with a good graphics card gives
noticeably sharper answers than one without. The *finding* half works well on
any machine, and there's a mode below that skips the AI entirely.

---

## What you'll need

| | |
|---|---|
| **Disk space** | About 6 GB, mostly the AI model |
| **Memory** | 16 GB of RAM is comfortable. 8 GB works with a smaller model |
| **Python** | Version 3.11 or newer — free, installed once |
| **Ollama** | Free, installed once. This is what runs the AI locally |
| **Internet** | Only during setup. Never again after that |

---

## Setting it up

Four steps. Take them in order.

### 1. Install Python

Go to **<https://www.python.org/downloads/>** and install the latest version.

> **On Windows, this one thing matters:** on the very first screen of the
> installer there's a checkbox that says **"Add python.exe to PATH"**. Tick it
> before you click Install. If you miss it, nothing else will work, and the fix
> is to run the installer again and tick it.

On a Mac you may already have Python. It does no harm to install the current
version anyway.

### 2. Install Ollama

Go to **<https://ollama.com>** and install it. This is the program that runs the
AI model on your own machine instead of someone else's server.

Once it's installed, open a terminal —

- **Windows:** press Start, type `cmd`, press Enter
- **Mac:** press Cmd+Space, type `Terminal`, press Enter

— and run this, which downloads the AI model itself:

```bash
ollama pull llama3.1:8b
```

That's about 5 GB and takes a few minutes. It happens once. (If your computer is
older or newer than average, see [Choosing a model](#choosing-a-model-for-your-computer)
below — you may want a different one.)

Leave Ollama running. On Windows and Mac it starts with your computer and sits
quietly in the menu bar or system tray.

### 3. Get Storykeeper onto your computer

```bash
git clone https://github.com/cgbeaulieu/storykeeper.git
```

Or download the ZIP from that page and unzip it somewhere you'll remember.
Either way you end up with a folder called `storykeeper`.

### 4. Run the setup script

Open that folder and run the setup script for your system:

- **Windows:** double-click **`setup.cmd`**
- **Mac / Linux:** open a terminal in that folder and run **`./setup.sh`**

It creates a private Python environment inside the folder and installs the four
pieces Storykeeper needs. It doesn't change anything else on your computer, and
it never touches your writing. It takes a minute or two and needs the internet.

**On Windows**, then double-click **`finish-setup.cmd`**. It downloads the AI
model named in the settings (if you haven't already) and checks that every
piece is talking to the others.

When it finishes, you're set up.

> **Windows shortcut:** after setup you never need to open a terminal.
> Double-click **`index-my-writing.cmd`** to read your writing in, and
> **`ask-storykeeper.cmd`** to start asking questions. The commands below do the
> same things, plus a few more.

---

## Using it

Open a terminal **in the Storykeeper folder** and type the commands below.

> **Windows:** type `.\storykeeper` — with the `.\` at the front. That tells
> Windows to look in the folder you're in.
> **Mac / Linux:** type `./storykeeper.sh` instead.
>
> Everything below is written the Windows way. Swap in `./storykeeper.sh` if
> you're on a Mac.

### Put your writing in the library folder

Inside the Storykeeper folder there's a folder called `library`. Put your files
in there, sorted into these subfolders:

```
library/
  manuscript/     the book itself — chapters, drafts, scenes
  characters/     character sheets, backstories, voice notes
  history/        timelines, past events, backstory of the world
  culture/        religion, language, customs, politics, factions
  locations/      places, maps, geography, buildings
  plot/           outlines, beat sheets, structure notes, what-ifs
  other/          anything that doesn't fit above
```

The folder a file sits in tells Storykeeper what kind of material it is, which
helps it answer the right way — a question about someone's appearance should
look at your character notes first, and a question about what actually happens
in chapter twelve should look at the manuscript.

Sub-subfolders are fine. You don't have to use every folder, and you don't have
to reorganise anything you already have. If in doubt, put it in `other/` — it's
still fully searchable.

**File types it reads:** `.txt`, `.md`, `.docx` (Word), `.rtf` and `.rtfd`
(TextEdit), `.odt`, `.pdf`, and Scrivener projects (`.scriv`). Scanned PDFs —
pictures of pages rather than text — can't be read; a quick test is whether you
can select a sentence in it with your mouse.

### Read it in

```bash
.\storykeeper index
```

The first run takes a minute or two and downloads a small search model (about
130 MB — the last thing it will ever download). Every run after that takes
seconds, because it only re-reads what changed.

Run this again after a writing session. If you forget, `status` will tell you.

### Ask a question

```bash
.\storykeeper ask "what colour are Maren's eyes?"
```

You'll get an answer with numbered citations, and the list of files they came
from. To see the actual passages behind the answer, add `-s`:

```bash
.\storykeeper ask -s "how does the guild choose its next master?"
```

That's the mode to use when the answer matters. It shows you exactly what the AI
was looking at, so you can judge for yourself instead of taking its word.

To skip the AI entirely and just see what your files say — much faster, and
useful on a slower computer:

```bash
.\storykeeper ask --no-llm "the winter crossing"
```

### Have a conversation

```bash
.\storykeeper chat
```

This keeps the thread, so you can follow up:

```
> Who is Kestrel?
  ...
> What colour is her hair?
  ...
```

Inside a chat you can type:

| | |
|---|---|
| `/sources` | show or hide the passages behind each answer |
| `/k 12` | look at more passages per question (default is 8) |
| `/type character` | only look at one kind of material |
| `/type all` | go back to looking at everything |
| `/new` | forget the conversation so far |
| `/quit` | leave (or just type `exit`) |

### Find exact words

```bash
.\storykeeper find "Ninefold Court"
```

No AI, no interpretation — just every place those words appear, with the file
and a line of context. It ignores capitals and curly-vs-straight quotes, so
`don't` finds `don’t`.

### Check on things

```bash
.\storykeeper status
```

Tells you how much is indexed, when it was last updated, whether any files have
changed since, and whether Ollama is running.

---

## Choosing a model for your computer

The default is `llama3.1:8b`, which suits a typical machine with 16 GB of RAM.
If yours is different, pick from this table and download it with
`ollama pull <name>`. Then, in the Storykeeper folder, create a plain text file
called `storykeeper.local.toml` containing:

```toml
[llm]
model = "mistral-nemo:12b"
```

— with your chosen model's name. Settings in that file override the shipped
`storykeeper.toml`, and keeping them separate means updating Storykeeper later
never overwrites your choice. (On Windows, `finish-setup.cmd` will download
whichever model this file names.)

| Your computer | Try | What to expect |
|---|---|---|
| 8 GB RAM, no graphics card | `llama3.2:3b` | Finds well, summarises poorly. Fast |
| 16 GB RAM, no graphics card | `llama3.1:8b` | The default. Solid for lookups, slow-ish |
| 8–12 GB of video memory | `mistral-nemo:12b` | Noticeably better reasoning |
| 16–24 GB of video memory | `qwen2.5:32b` | Genuinely good |

Model names change over time. If one of these doesn't exist any more, look at
<https://ollama.com/library> for the current equivalent — anything with a long
context window will do.

Not sure what your machine has? Run `.\storykeeper ask --no-llm "anything"`
first. If the *finding* works well, the search half is fine, and the model
choice only affects how the answer is written up.

---

## Troubleshooting

**"Ollama is not running"**
Open the Ollama app — on Windows and Mac it lives in the system tray or menu
bar. Or run `ollama serve` in a terminal and leave that window open.

**"The AI model ... is not installed"**
Run the `ollama pull` command it prints, once. It's a large download.

**"Nothing has been indexed yet"**
Put files in `library/` and run `.\storykeeper index`.

**Windows says `storykeeper` is not recognised**
Type `.\storykeeper` — with the dot and backslash at the front. And make sure
your terminal is in the Storykeeper folder.

**The answer is vague, or misses something you know you wrote**
Three things to try, in order:

1. Run `.\storykeeper find "the exact words"` to confirm it's actually indexed.
   If `find` doesn't see it, `index` hasn't read it yet.
2. Ask again with `-s` and look at the passages. If the right passage is there
   but the answer is poor, that's the AI model — try a bigger one.
3. Ask for more passages: `.\storykeeper ask -k 15 "..."`.

**It gets two characters mixed up**
Almost always a formatting thing. Storykeeper splits your notes on headings and
blank lines to keep each person separate. Putting each character under their own
heading (`# Maren Vesh`) makes this reliable.

**Answers are extremely slow**
Normal without a graphics card. Use a smaller model, or use `--no-llm`, which
skips the AI and is instant.

**"Reading PDFs needs one extra piece"**
The PDF reader didn't get installed — usually because Storykeeper was set up
with an older version. Run the setup script again; it's safe, and it won't touch
your writing.

**"No text could be pulled out of this PDF"**
It's a scan — a picture of a page rather than words. Storykeeper can't read
those.

**Google Docs, Apple Pages, old `.doc` files, OneNote**
Storykeeper will tell you what to do when it meets one. In short: export or save
a copy as `.docx` and put that in `library/`. Google Docs in particular has no
file on your computer to read — the writing is on Google's servers, and going to
fetch it is exactly the thing this tool is built not to do.

**Something else went wrong**
Rebuilding the index is always safe. It never touches your writing:

```bash
.\storykeeper index --rebuild
```

---

## Where your writing goes (the short version: nowhere)

- Your files stay in `library/`. Storykeeper reads them and never writes to them.
- The search index goes in `index/` — passages of your text plus a list of
  numbers per passage. Also on your computer only.
- Both folders are excluded from version control, so they can't be uploaded by
  accident even if this folder is in a Git repository.
- The AI model runs inside Ollama on `localhost` — your own machine, talking to
  itself.
- Two downloads happen during setup and never again: the search model (~130 MB)
  and the AI model (~5 GB). After the first successful run, Storykeeper puts the
  search library into offline mode so it can't check for updates either.

You can verify all of this by unplugging your network and using it normally.

---

## For the curious

- `storykeeper.toml` holds every setting, with a comment explaining each one.
  To keep your own tweaks separate, copy it to `storykeeper.local.toml` and edit
  that — it overrides the original, setting by setting.
- `SPEC.md` explains how the whole thing works and why it was built this way.
- Run the tests with `.venv\Scripts\python -m unittest discover -s tests`
  (or `.venv/bin/python ...` on Mac and Linux).

## Contributing

Issues and pull requests are welcome. One rule outranks everything else:
**nothing may leave the user's machine while indexing or answering.** A change
that adds a network call, a hosted service, or a dependency with telemetry on by
default won't be merged, however much it improves the answers. `CLAUDE.md` and
`SPEC.md` say more, including how new dependencies are vetted.

Please never attach real manuscript material to an issue. Make up a small
example that shows the problem instead.

## License

[MIT](LICENSE).
