"""
Memory Companion: pointer-based associative memory for heartbeat pulses.

Fires on UserPromptSubmit hook. Scans the pulse prompt and run narrative
for topics, queries RAG (BM25-only, fast), and injects brief pointers
to relevant past context. The pulse instance decides whether to follow up.

Does NOT inject memory content — only suggests queries. The model's own
intelligence decides what's worth retrieving.
"""
