# L'Intello — User Stories

## Chat & AI Routing

**US-01**: As a user, I want to ask a question and get the best available answer without choosing a model, so I can focus on my work instead of managing AI providers.

**US-02**: As a user, I want to see which model answered and how much it cost, so I can understand what I'm using.

**US-03**: As a user, I want my conversations saved and resumable, so I can continue where I left off.

**US-04**: As a user, I want to rate responses, so the system learns which models work best for which tasks.

**US-05**: As a user, I want streaming responses, so I don't stare at a blank screen for 30 seconds.

**US-06**: As a user, I want to choose between Fast (single model), Deep (cross-review), Debate (adversarial), and Auto modes.

## Literary Analysis

**US-10**: As a writer, I want to upload a manuscript (TXT, PDF, EPUB) and see its structure, pacing, and characters automatically.

**US-11**: As a writer, I want a tension/pacing curve showing where my story is fast or slow.

**US-12**: As a writer, I want narrative threads visualized as colored bars showing where questions are raised and resolved.

**US-13**: As a writer, I want character extraction that finds full names (not just first names) and tracks their appearances.

**US-14**: As a writer, I want AI-powered analysis that gives specific, line-level edit suggestions.

**US-15**: As a writer, I want to accept or reject each suggested edit individually.

**US-16**: As a writer, I want to export my document as HTML (editable) or DOCX.

## Writing Tools

**US-20**: As a writer, I want to select text and convert "telling" to "showing" with one click.

**US-21**: As a writer, I want to describe any element using all five senses.

**US-22**: As a writer, I want to shift the tone of a passage (darker, funnier, more intimate).

**US-23**: As a writer, I want to brainstorm plot ideas, characters, twists, settings, or dialogue from a seed.

**US-24**: As a writer, I want to compress my manuscript into a logline, blurb, synopsis, or pitch.

**US-25**: As a writer, I want 3 AI beta readers (casual, craft expert, literary agent) to review my work simultaneously.

**US-26**: As a writer, I want to generate a first draft from a scene description.

## Writing Workflow

**US-30**: As a writer, I want a project brief (genre, style, target length, character arcs, themes) that guides all AI analysis.

**US-31**: As a writer, I want the system to auto-detect my writing style, characters, and themes from the text.

**US-32**: As a writer, I want an adaptive "Next Step" button that knows whether I need an outline, structure enrichment, or text expansion.

**US-33**: As a writer, I want horizontal mode (expand text) and vertical mode (enrich structure).

**US-34**: As a writer, I want to control how much of my daily credits to spend per request (1%/10%/50%/100%).

**US-35**: As a writer, I want to save progress and resume the next day when credits reset.

**US-36**: As a writer, I want craft techniques injected into analysis prompts, varying each time for fresh perspectives.

**US-37**: As a writer, I want word count enforcement — the AI must actually write the words, not describe them.

## Version Reconstruction

**US-40**: As a user with 50+ version files scattered across Google Drive, I want to select them all and ingest them in one batch.

**US-41**: As a user, I want the system to detect cross-references ("unchanged since v21") and pull content from the right version.

**US-42**: As a user, I want a reconstructed complete document with confidence levels per section.

**US-43**: As a user, I want an LLM to smooth transitions between sections pulled from different versions.

## OCR

**US-50**: As a user, I want to OCR a scanned PDF and get searchable text.

**US-51**: As a user, I want automatic quality escalation — if Tesseract fails, try cloud OCR, then Gemini Vision.

**US-52**: As a user, I want async OCR for large books (200+ pages) with progress tracking.

## Corkboard

**US-60**: As a writer, I want to see my chapters as index cards on a visual board.

**US-61**: As a writer, I want to drag and drop cards to reorder scenes.

**US-62**: As a writer, I want to write a synopsis on each card.

## Integration

**US-70**: As a developer, I want an OpenAI-compatible API so any client can use L'Intello as a drop-in replacement.

**US-71**: As an external clients admin, I want L'Intello to provide AI features (book chat, recaps, search) via HTTP.

**US-72**: As a developer, I want webhooks so external services can trigger L'Intello actions.

**US-73**: As an admin, I want scheduled tasks that run automatically (daily summaries, monitoring).

## Admin

**US-80**: As an admin, I want to add API keys at runtime without restarting.

**US-81**: As an admin, I want to see rate limit usage across all providers.

**US-82**: As an admin, I want one-click backup of all data.

**US-83**: As an admin, I want premium models restricted to specific users.
