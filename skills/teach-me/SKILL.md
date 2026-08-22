---
name: teach-me
description: Turn source-code learning requests into evidence-backed interactive HTML lessons and serve them locally. Use when the user wants to read, understand, trace, or learn a codebase, module, algorithm, protocol, or implementation through its source. Do not use for ordinary implementation, debugging, or review unless learning how the code works is a primary goal.
---

# Teach Me

Turn source reading into a durable learning artifact. Make the HTML lesson the
primary deliverable and keep the conversational handoff concise.

## Build the lesson

1. Establish the learning question and evidence trail.
   - Infer the learner's goal and depth from the request; ask only when different
     interpretations would produce materially different lessons.
   - Locate the real entry points and trace only the source needed to answer that
     question. Use an existing codebase map or repository guide as a locator when
     available, then verify every path and symbol against current source.
   - Record the entry, important calls, state or data transformations, branches,
     outcomes, and relevant failure paths. Label interpretation separately from
     behavior established by source.

   This step is complete when the main flow can be explained from entry to effect
   with a source coordinate for every important transition.

2. Shape the page around **Map, Trace, Practice**.
   - **Map:** give a one-screen mental model of the problem, the participating
     components, and where they live in the repository.
   - **Trace:** make the execution or data flow explorable with a stepper,
     timeline, state transition, or another interaction suited to the topic.
     Pair each step with its file, symbol, and meaningful before/after state.
   - **Practice:** add small knowledge checks, prediction prompts, a glossary,
     and a focused "read next" path. Keep answers revealable rather than visible
     by default.
   - Match the learner's language and apparent prior knowledge. Preserve source
     identifiers verbatim and define unfamiliar terms before first use.
   - Adapt the visual model to the material: emphasize invariants and state for
     algorithms, request/data flow for systems, and terminology for a new domain.

   Each visual or interaction must teach a verified relationship; decoration is
   secondary to comprehension.

3. Create the learning artifact.
   - Use a user-specified destination when provided. Otherwise write
     `<workspace-root>/.teach-me/<topic-slug>/index.html`, updating an existing
     lesson for the same topic instead of creating a duplicate.
   - Default to one self-contained, offline page with inline CSS, JavaScript, and
     SVG. Use no CDN, package install, build step, or network dependency unless
     the user requests a multi-file application.
   - Make it responsive and accessible: semantic landmarks, keyboard-operable
     controls, visible focus, sufficient contrast, and reduced-motion support.
   - Keep excerpts short. Show repository-relative paths, symbols, and current
     line spans beside excerpts so the learner can return to the source. Mark
     line spans as snapshot coordinates when they may drift.
   - Exclude secrets, generated output, and source unrelated to the learning
     question.

4. Verify and serve.
   - Render the page with available browser tooling. Check the narrow and wide
     layouts, every main interaction, and the browser console; repair observable
     problems before handoff.
   - Start the bundled server with:

     ```bash
     python3 <teach-me-skill-dir>/scripts/serve.py <lesson-directory>
     ```

     It binds to loopback and chooses an available port by default. Keep the
     process running when the environment supports long-lived commands.
   - Open or report the printed URL and provide the absolute path to `index.html`.
     If a long-lived process cannot be retained, provide the exact server command
     for the user to run.

The task is complete when the lesson loads over HTTP, its core flow agrees with
the cited source, and its Map, Trace, and Practice interactions work. When the
user explicitly requests text only, honor that format and skip the artifact and
server.
