"""Writing tools — AI-powered text transformations powered by multi-LLM routing."""


def show_not_tell(text: str, context: str = "") -> str:
    """Convert telling prose to showing prose."""
    return f"""Rewrite this passage to SHOW instead of TELL. Replace emotional labels with physical actions, sensory details, and behavior that reveals the emotion.

{f"CONTEXT: {context}" if context else ""}

ORIGINAL:
{text}

RULES:
- Replace "she was angry" with what anger LOOKS like (clenched jaw, slammed door)
- Replace "the room was beautiful" with specific visual details
- Keep the same meaning and plot points
- Maintain the original POV and tense
- Do NOT add new plot events

REWRITTEN (show, don't tell):"""


def describe_senses(element: str, context: str = "") -> str:
    """Describe an element using all five senses + metaphor."""
    return f"""Describe this story element using all five senses plus a metaphor.

ELEMENT: {element}
{f"CONTEXT: {context}" if context else ""}

Provide vivid, specific descriptions for each:
1. SIGHT: What does it look like? Colors, shapes, light, movement.
2. SOUND: What sounds does it make or are associated with it?
3. SMELL: What scents surround it?
4. TOUCH: What does it feel like? Temperature, texture, weight.
5. TASTE: Any taste associations? (even metaphorical)
6. METAPHOR: One striking metaphor that captures its essence.

Be specific and evocative. Avoid clichés."""


def tone_shift(text: str, target_tone: str) -> str:
    """Rewrite a passage in a different tone."""
    return f"""Rewrite this passage in a {target_tone} tone. Keep the same events and meaning, but shift the emotional register and word choice.

ORIGINAL:
{text}

TARGET TONE: {target_tone}

REWRITTEN ({target_tone} tone):"""


def brainstorm(seed: str, category: str = "plot", genre: str = "fiction") -> str:
    """Generate creative ideas from a seed."""
    prompts = {
        "plot": f"Generate 5 compelling plot developments that could follow from this seed. Each should be surprising but logical. Include one twist nobody would expect.\n\nSEED: {seed}\nGENRE: {genre}",
        "character": f"Generate 5 detailed character concepts that could exist in this story world. For each: name, key trait, contradiction, secret, and how they connect to the story.\n\nSEED: {seed}\nGENRE: {genre}",
        "twist": f"Generate 5 plot twists for this story. Range from subtle to shocking. Each must be foreshadowable and logically consistent.\n\nSEED: {seed}\nGENRE: {genre}",
        "setting": f"Generate 5 vivid settings/locations for this story. For each: name, atmosphere, what makes it unique, and what conflict it enables.\n\nSEED: {seed}\nGENRE: {genre}",
        "dialogue": f"Generate 5 key dialogue exchanges that could occur in this story. Each should reveal character AND advance plot simultaneously.\n\nSEED: {seed}\nGENRE: {genre}",
    }
    return prompts.get(category, prompts["plot"])


def shrink_ray(text: str, target: str = "blurb") -> str:
    """Compress text into various summary formats."""
    targets = {
        "logline": "a single sentence (25-35 words) that captures the core conflict and stakes",
        "blurb": "a back-cover blurb (100-150 words) that hooks the reader without spoiling the ending",
        "synopsis": "a full synopsis (300-500 words) covering all major plot points including the ending",
        "outline": "a chapter-by-chapter outline with one sentence per chapter",
        "pitch": "a 3-sentence elevator pitch: hook, conflict, stakes",
    }
    fmt = targets.get(target, targets["blurb"])
    return f"""Compress this text into {fmt}.

TEXT:
{text[:8000]}

Generate the {target.upper()}:"""


def first_draft(scene_description: str, style: str = "", word_count: int = 1000) -> str:
    """Generate a first draft from a scene description."""
    return f"""Write a first draft of this scene. Approximately {word_count} words.

SCENE: {scene_description}
{f"STYLE: {style}" if style else ""}

RULES:
- Write the ACTUAL prose, not a summary or outline
- Include dialogue, action, and sensory details
- Start in the middle of the action (in medias res)
- End with a hook or unresolved tension
- Target: {word_count} words — count them

FIRST DRAFT:"""


def beta_reader_prompt(text: str, reader_type: str) -> str:
    """Generate a beta reader perspective."""
    readers = {
        "casual": "You are a casual reader who reads for entertainment. You care about: Is it fun? Does it keep me turning pages? Do I care about the characters? Are there boring parts I'd skip? Be honest and conversational.",
        "craft": "You are a writing workshop instructor with 20 years of experience. You care about: prose quality, pacing, structure, character development, theme, and technical craft. Be specific and cite examples from the text.",
        "market": "You are a literary agent evaluating this for publication. You care about: marketability, genre fit, hook strength, comparable titles, and what would make an editor say yes or no. Be blunt about commercial viability.",
        "sensitivity": "You are a sensitivity reader. You care about: representation accuracy, potential harmful stereotypes, cultural authenticity, and whether diverse characters feel three-dimensional. Be constructive.",
        "genre": "You are an avid genre reader who has read 500+ books in this genre. You care about: genre conventions (are they met or subverted well?), tropes (fresh or stale?), and how this compares to the best in the genre.",
    }
    persona = readers.get(reader_type, readers["casual"])
    return f"""{persona}

Read this text and provide your honest feedback:

TEXT:
{text[:6000]}

Provide:
1. Your overall reaction (2-3 sentences, gut feeling)
2. What worked best (specific moments/lines)
3. What didn't work (specific issues)
4. Where you got bored or confused
5. One thing that would make you keep reading / stop reading
6. Rating: 1-10 with justification"""
