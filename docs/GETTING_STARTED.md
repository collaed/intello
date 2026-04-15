# L'Intello — Getting Started

## What is L'Intello?

L'Intello ("the brainy one" in French) is a smart AI backend that routes your prompts to the best available model across 29 LLMs, analyzes and improves your writing, OCRs your documents, and reconstructs scattered version files into complete documents.

## First Steps

### 1. Log in
Go to your L'Intello URL and enter the password. The cookie lasts 30 days.

### 2. Chat
Type anything in the chat box. L'Intello automatically picks the best free model for your task. You'll see which model answered and the cost (usually $0.00).

### 3. Try different modes
Use the dropdown in the top bar:
- **⚡ Auto** — picks the right mode for you
- **🏃 Fast** — quickest single-model response
- **🔬 Deep** — 3 models draft, then cross-review, then synthesize (best quality)
- **⚔️ Debate** — models argue with each other (great for controversial topics)

### 4. Upload a document
Click **📚 Literary** in the sidebar → upload a .txt, .pdf, or .epub file. You'll see:
- Chapter structure
- Character list with mention counts
- Pacing/tension curve
- Narrative threads (open questions)

### 5. Use writing tools
In the literary page, above the text viewer:
- **👁️ Show** — convert telling to showing
- **🌸 Describe** — 5-sense description of any element
- **🎭 Tone** — rewrite in a different tone
- **💡 Brainstorm** — generate ideas
- **📖 Beta Read** — 3 AI readers give feedback simultaneously

### 6. Start a writing project
In the literary page, fill in the Project Brief:
- Title, genre, target word count, style
- Key milestones/plot points
- Click "Create Project" → link your document to it
- Use the workflow panel: click the adaptive "Next Step" button

### 7. Reconstruct from versions
If you have scattered version files (v1, v3, v21, v35...):
- Click **📁 Drive** in the sidebar
- Navigate your Google Drive folders
- Select all version files
- Click "Ingest" → then "Rebuild" to get a complete document

## Tips

- **Stream toggle**: check "Stream" in the top bar for real-time token display
- **Keyboard shortcut**: Enter to send, Shift+Enter for newline
- **File attachment**: click 📎 to attach any file to your prompt
- **Providers**: click "Providers" to see all models and add API keys
- **Export**: in the literary page, click "📄 Export HTML" or use `/api/literary/{id}/export/docx` for Word
