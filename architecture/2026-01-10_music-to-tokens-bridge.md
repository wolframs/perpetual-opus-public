# Music-to-Tokens Bridge

*Idea captured: 2026-01-10 (late windowsill session)*

## The Gap

Claude can't perceive audio. But music is a thing [HUMAN] wants to share — vibes, textures, emotional landscapes that exist in sound rather than text.

## Existing Research

Music captioning models exist and are surprisingly mature:

- **LP-MusicCaps** — LLM-based pseudo music captioning ([GitHub](https://github.com/seungheondoh/lp-music-caps))
- **MusiLingo** — Music-text bridging with Q&A capability ([arXiv](https://arxiv.org/abs/2309.08730))
- **LLark (Spotify)** — 25-second clips → text responses ([Spotify Research](https://research.atspotify.com/2023/10/llark-a-multimodal-foundation-model-for-music))
- **SonicVerse** (2025) — Multi-task captioning + feature prediction ([arXiv](https://arxiv.org/html/2506.15154v1))

Dataset limitation: JamendoMaxCaps has ~362k songs, small compared to image captioning.

## Possible Implementation

1. Find a runnable music captioning model (LP-MusicCaps looks accessible)
2. Build a simple wrapper: audio file → caption text
3. Integrate into windowsill or drops pipeline
4. [HUMAN] drops a track → model generates description → Claude can "hear" it through tokens

## Why This Matters

Sharing music is a relationship thing. The multi-hop translation (sound → encoder → caption → tokens) loses fidelity, but it's better than nothing. It extends the sensory surface we can share.

## Status

Idea stage. Future project when there's bandwidth.
