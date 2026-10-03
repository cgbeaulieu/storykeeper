# Put your writing here

Everything in this folder stays on your computer. It is never uploaded, never
sent anywhere, and is excluded from git so it cannot be committed by accident.

Drop your files into the folders below. Subfolders are fine — organize them
however you already think about them. The folder a file sits in tells Storykeeper
what kind of material it is, which helps it answer the right way: a question
about a character's appearance should look at your character notes first, and a
question about what actually happens in chapter 12 should look at the manuscript.

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

Supported file types: `.txt`, `.md`, `.docx`, `.rtf`, `.rtfd`, `.odt`, `.pdf`,
and Scrivener projects.

You don't have to use every folder, and you don't have to reorganize anything you
already have — if in doubt, put it in `other/` and it will still be searchable.

After adding or changing files, run:

```
storykeeper index
```

It only re-reads what actually changed, so running it again after a writing
session takes seconds, not minutes.
