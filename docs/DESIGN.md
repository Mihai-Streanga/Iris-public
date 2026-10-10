# Iris — design decisions

This document explains how Iris is built and why: the principles behind the code and the
decisions that were closed during development, each with its reason. Most of them were settled
by measurement on a corpus of the author's recorded dictations; the corpus and the benchmark
scripts stay in the private repository (see [Known limitations](../README.md#known-limitations)),
so the figures here are quoted, not reproducible from this repository.

## 1. Scope and non-goals

Iris **types what you said** where the cursor is, and stops. It never sends: `Enter` stays with
the person, who reads the text before it goes anywhere.

Non-goals: automatic sending, a silence threshold that ends the dictation by itself, streaming
text while you talk (section 6); any network layer; downloading models silently (section 8).

## 2. Principles

**Nothing leaves the machine.** No network call in the code. Audio is read into memory and never
written to disk; dictations are not saved. The only file written in use is the window position
(`stare.json`).

**The model proposes; code cleans; the person decides.** Whisper proposes the text. Cleanup
(collapsing whitespace, filler sounds, known hallucinations) is deterministic code. `Enter` is the
person's.

**Whisper cannot say "I heard nothing".** On silence it produces text, typically a "thanks for
watching" sentence. So everything the model produces goes through deterministic code before it
reaches the person, and that code is the only door: Iris has no chat in which to ask again.

**Accuracy beats speed, and the verdict is automatic.** Every engine setting is measured on the
corpus, and the acceptance criterion is written in code: a tuning is rejected at the first word
lost, however much faster it is. The one exception is written down as such (section 3).

**Verification is decided by area.** Transcription, the route, the pre-encoding and the cleanup
are mechanical: they are checked on the corpus, with an automatic verdict. The window, the
colours, the sounds, focus and `SendInput` are human: they need a real Windows session and eyes.

**One configuration file.** Everything configurable is in `iris.json`, read once at startup.

**One change at a time.** No stage starts until the previous one is in real use, and each
correction changes a single variable.

## 3. The route and the pre-encoding

- **The iGPU route stays on, as a written exception to the criterion.** On the 45 corpus clips
  under the boundary it is 7.9× faster (0.63 s median against 5.15 s) and gets 2 of 45 wrong
  (4.4%) where the CPU engine got them right. The criterion rejects it, and the criterion is not
  rewritten to let it pass: every measurement round reports the route as rejected, and that is
  how it should be. `"granita_igpu": 0` turns it off. Only beam search on OpenVINO would reopen it.
- **The boundary does not go below 30 s.** The iGPU errors sit at 4.9, 14.2, 17.6 and 23.5 s; a
  lower boundary would not avoid them.
- **Pre-encoding is on by default.** On the 7 corpus clips over 30 s, 18 encoder calls become 11
  and the wall-clock time falls by 39.4%, with zero words changed. `"devans": false` turns it off.
- **Only the first window is pre-encoded.** Where later windows start is not known in advance:
  decoding jumps to the last timestamp of the window before.
- **Loading: iGPU first, then CPU, both at startup.** The other order cost 23.5% on a pass.

## 4. Model parameters

| Setting | Decision | Why |
|---|---|---|
| `cpu_threads` | 8 | 4 and 6 are slower (+21%, +8%); 12 and 16 are within noise |
| `compute_type` | `int8` | `int8_float32` is within noise; `float32` costs 45% more and loses a word |
| `beam_size` | 5 | 1 loses two words to gain 5% |
| batched pipeline | not used | loses five words and forces `condition_on_previous_text=False` |
| `hotwords` | kept | without it, 12 of 32 clips break, with a "cloud cloud cloud" loop |
| `hotwords` content | merged with the vocabulary of [JA.S.Mine](https://github.com/Mihai-Streanga/Jasmine-public) | fixes two phrases on the iGPU route at equal time, and loses the diacritics on one |
| JA.S.Mine's prompt | not used | on the CPU it breaks "Claude Code", loses words and adds 19–20 s on a 73.4 s clip |
| `no_repeat_ngram_size` | not used | on CTranslate2, n=2 fixes a duplication and breaks 26 words; on OpenVINO it is inert |
| `repetition_penalty` (OpenVINO) | not used | 1.05 loses 5 more words, 1.1 loses 9 |
| `vad_filter` | on | free on all three engines tried; without it, English terms come out mangled |
| decoding defaults | kept | the faster combination saves 0.14 s and deletes five words on long clips |
| whisper.cpp | not used | faster on short commands, but loses capitals; speed buys nothing when `Enter` is the person's |
| warm-up | without VAD | with VAD the warm-up took 0.00 s, which means it warmed nothing |

## 5. The window and Windows

- **Unicode `SendInput`, not clipboard plus `Ctrl+V`.** `Ctrl+V` does not paste in every terminal,
  and the clipboard would be overwritten at every sentence. The clipboard is used only as the
  fallback when the target window refuses the text, and the window says so.
- **`RegisterHotKey`, not a keyboard hook.** A global hook that hangs blocks the keyboard
  everywhere. No `keyboard` or `pynput`.
- **A single instance is a named mutex, not a lock file.** A file would survive a crash.
- **A second launch signals the first, and Tk restores itself.** `ShowWindow` from another process
  leaves Tk convinced it is minimized, and the second process has no right to the foreground.
- **The frame is removed through the window style, not with `overrideredirect`**, with which Tk
  refuses to minimize.
- **Transparency is a premultiplied `UpdateLayeredWindow`, not a colour key**, which gives either
  a jagged edge or a halo in the key colour.
- **The state colours are the author's choice**, made by looking at all five together, not by
  convention. The pulsar does not shrink while transcribing: a change of size read as "another
  tool". The text outline is one pixel; at two it looks like a sticker.
- **No tray icon.** The taskbar button does the same job.
- **Pinning to the taskbar is not automated.** The verb is missing on Windows 11 25H2, and the
  taskbar's private registry keys are not touched.

## 6. The text

- **Repeated words are not removed.** "very very" can be right, and a missing word is not noticed.
- **Hallucinations are removed only as whole sentences**, never as a substring.
- **The VAD thresholds are not tuned without an audio capture**, and a capture needs the
  author's consent.
- **No automatic sending, no silence threshold, no streaming.** `Enter` and the end of a sentence
  are the person's; chunks of 2–3 s break English terms in Romanian speech.

## 7. The sounds

- **Synthesized** by `fa-sunete.py`, not taken from `C:\Windows\Media` and not `winsound.Beep`.
  Regeneration is deterministic; old sets are kept, and `iris.json` says which one is in use.
- **Normalized by RMS, not by peak**, to a target of 0.20 at volume 1.0.

## 8. The environment

- **Models load with `local_files_only=True`.** A missing model is a refusal, never a silent
  download.
- **No dependencies for small things:** the icon PNG is written by hand, Windows is reached
  through `ctypes` and GDI.
- **`av` is pinned to 18.0.0**, because newer versions were blocked by Windows App Control; the
  re-check command is in `requirements.txt`.
- **Memory stays at about 3.3 GB** with both engines loaded. The author decided not to trade
  accuracy or speed to lower it.

## 9. What was tried and buys nothing

- **The NPU:** it fails on static shapes, and decodes greedily anyway.
- **Beam search on the iGPU:** not implemented in OpenVINO 2026.3 or 2026.4.1; this is where the
  route's errors come from. Retried when a version announces it.
- **`KMP_AFFINITY`, `OMP_PROC_BIND`**, and importing OpenVINO as a CPU accelerator.
- **Normalizing hyphens, spaces and digits in the verdict:** a normalization that joins hyphens
  could hide a real lost word, so those artefacts are sorted by hand.

## 10. What is not in this repository

The corpus of recorded dictations, the benchmark scripts and the measurement log stay private:
the corpus is the author's voice. So do the project's working notes and the full log of lessons
behind the decisions above.
