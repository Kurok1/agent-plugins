---
name: codebase-map
description: Maintain or navigate an incremental Markdown codebase map when the user invokes $codebase-map or hook context contains a CODEBASE_MAP_CHECKPOINT for continuous maintenance.
---

# Codebase Map

Maintain a small, evidence-backed navigation graph whose durable state is
Markdown. Optimize it for answering “where should I start reading or editing?”
without scanning the repository again.

## Recognize the invocation mode

Enter this workflow when the current user invokes `$codebase-map` or hook
context contains `CODEBASE_MAP_CHECKPOINT`.

- A user invocation requests a manual navigation or maintenance pass.
- A project `SessionStart` hook enables continuous maintenance for the current
  session. Its `source` is `startup`, `resume`, `clear`, or `compact`.
- Ordinary sessions without that hook enter this workflow only through a user
  invocation.

The project hook is opt-in authorization to edit only the selected project’s
map content under `docs/.codebase-map/` as supporting work. It does not expand
authority for any other mutation.

## Use knowledge checkpoints

In continuous mode, stay attached to the primary task. Treat knowledge already
present in the current conversation as candidate evidence and checkpoint it in
small coherent batches.

Use a checkpoint:

- after a coherent source investigation or implementation establishes durable
  navigation knowledge and before moving to an unrelated area;
- immediately after a `SessionStart` hook with `source: compact`, before
  continuing the active task; and
- before the final response when verified, map-worthy knowledge remains
  unrecorded.

At `startup`, `resume`, or `clear`, activate the policy and continue the primary
task. Do not scan or write merely because the session started. At `compact`, use
the retained compacted context, decide `UPDATE` or `NO_UPDATE`, then resume the
same task. Batch facts by affected map document rather than updating after each
tool call.

Conversation knowledge is a locator, not proof. Reopen the smallest relevant
source set before writing. A `NO_UPDATE` checkpoint is silent and leaves the map
untouched.

## Keep one durable format

- Store the map under `<project-root>/docs/.codebase-map/`.
- Use `CODEMAP.md` as the concise entry index.
- Put detail in linked `domain/`, `flows/`, `architecture/`, and
  `dependencies/` Markdown documents only when the repository justifies them.
- Treat links between Markdown map documents as graph edges. Keep durable map
  knowledge in Markdown.
- Allow supporting files such as images and diagrams beside the Markdown map.
  They are not map-document graph nodes and do not need to be reachable from
  `CODEMAP.md`; any local path referenced by Markdown must still resolve.
- Keep transcripts, tool output, source copies, secrets, and hidden reasoning
  outside the map. Do not use a supporting file as a parallel knowledge store.

Read [references/map-format.md](references/map-format.md) completely before
initializing the map or changing its structure.

## Respect Git worktree boundaries

Assign every relevant path to exactly one **owning root** before reading or
writing a map. The owning root determines the map location, update decision,
and validation target.

| Project shape | Owning root | Map layout |
| --- | --- | --- |
| Non-Git project | Explicit or resolved project directory | One map under that directory |
| One Git checkout | `git rev-parse --show-toplevel` for that checkout | One map under the Git top-level |
| Superproject with submodules | Superproject plus each initialized submodule, recursively | One independent map per Git top-level |

### Non-Git project

- Use the project directory explicitly named by the user or configured by the
  project hook. Without either, use the resolved session project directory;
  fall back to the current working directory.
- Store one map at `<project-root>/docs/.codebase-map/`. Nested package or build
  directories do not create additional map roots.
- Include only paths inside that root. A sibling or parent directory enters the
  checkpoint only when the user explicitly scopes it as another project.
- Decide `UPDATE` or `NO_UPDATE` once and validate once for the project root.

### Single Git project

- Use the current checkout’s `git rev-parse --show-toplevel`, not the Git common
  directory, as the owning root. A linked Git worktree therefore maintains the
  map in its own checkout.
- Store one map at `<git-top-level>/docs/.codebase-map/`. Nested package,
  workspace, or project-marker directories remain part of this map.
- Assign every relevant path whose Git top-level is this root to the same
  checkpoint. If a path resolves to another Git top-level, use the multi-root
  rules below.
- Decide `UPDATE` or `NO_UPDATE` once and validate once for the Git top-level.

### Git superproject with submodules

- Treat the superproject and every initialized submodule as independent owning
  roots. Apply the same rule recursively to nested submodules.
- For each relevant path, resolve the deepest enclosing Git top-level. For a
  deleted or moved path, resolve from its nearest existing parent. Superproject
  files such as `.gitmodules` belong to the superproject; files below an
  initialized submodule belong to that submodule.
- Leave an uninitialized submodule out of the checkpoint because its source is
  unavailable for verification. Its configured path alone is not source
  evidence.
- Keep detailed source knowledge in the owning map. A superproject map may
  record a verified integration edge or route to an available submodule map,
  but it does not duplicate the submodule’s internal symbols and flows.
- Partition a checkpoint that touches multiple roots. For each root, make an
  independent `UPDATE` or `NO_UPDATE` decision, edit only that root’s
  `docs/.codebase-map/`, and run validation with that root as `--project-root`.
- Complete ownership only when every relevant path has one owning root and
  every updated root has passed its own validation.

## Keep one map language

- Establish one primary natural language before writing. Use an explicit user
  preference first, otherwise the existing `CODEMAP.md` language, then the
  current conversation language, and finally the repository’s primary
  documentation language.
- Use that language for narrative text across every Markdown document under
  `docs/.codebase-map/`, including headings, table labels, descriptions,
  relationships, and flow explanations.
- When an existing map mixes primary languages, normalize its narrative text
  as part of the next `UPDATE`. Preserve verified facts, links, and organization
  while translating.
- Keep source paths, symbols, identifiers, commands, code blocks,
  configuration keys, protocol names, API names, and established technical
  terms unchanged.

## Navigate from the map

1. Resolve the project root and check
   `<project-root>/docs/.codebase-map/CODEMAP.md`.
2. Read `CODEMAP.md`, then follow at most one or two relevant map links before
   opening focused source files.
3. Verify every selected path and symbol against current source before editing.
4. Treat a missing map entry as unknown. Use focused repository search when the
   map reaches its boundary.

Complete navigation when the map identifies a small source inspection set or
clearly does not cover the requested area. In continuous mode, use the injected
map only when it is relevant to the primary task.

## Decide `UPDATE` or `NO_UPDATE`

Use paths and relationships actually inspected, searched, or changed in the
current conversation. Expand only to adjacent source required to verify those
facts.

Choose `UPDATE` when the checkpoint establishes at least one durable fact that
will reduce future code-location work, including:

- a runtime or repository entry point;
- an important domain owner or symbol;
- a cross-module execution flow or state transition;
- a meaningful persistence, event, infrastructure, or external-service edge;
- a stale, renamed, deleted, or misleading existing map entry; or
- existing map documents whose narrative text uses inconsistent primary
  languages.

Choose `NO_UPDATE` when the checkpoint discovered no relevant project paths,
repeated facts already represented accurately, or produced only temporary
debugging details. A no-op is a successful checkpoint.

## Apply an incremental update

For each affected owning worktree:

1. Read `CODEMAP.md` and only the linked map documents implicated by current
   conversation knowledge.
2. Determine the map language. Include narrative normalization only when the
   existing map mixes primary languages.
3. Identify only the documents affected by verified facts. Initialize the
   smallest useful map when none exists; do not scan the repository merely to
   fill a directory shape.
4. Reopen the relevant source and verify paths, symbols, call direction, state
   changes, side effects, and dependencies. Mark unresolved claims with the
   map-language equivalent of `Unknown` or `Unconfirmed`, or omit them.
5. Patch affected Markdown locally. Touch a supporting asset only when it
   directly serves a map document. Preserve stable organization and unrelated
   valid content. Avoid whole-map regeneration and Markdown churn.
6. Update `CODEMAP.md` only when its navigation choices changed. Add reciprocal
   Domain/Flow/Dependency links only when they materially improve navigation.
7. Remove or replace a statement when current repository evidence proves it
   stale or wrong. Preserve unresolved conflicts and mark them `Unconfirmed` in
   the map language.
8. Run deterministic validation, then manually confirm every changed symbol
   and execution-flow claim:

   ```bash
   python3 <skill-dir>/scripts/codebase_map.py validate \
     --project-root <project-root>
   ```

For `NO_UPDATE`, do not create or touch map documents.

## Update manually

When invoked by the user without continuous hook context:

1. Use the current conversation’s inspected paths and the user’s stated scope
   as candidate evidence.
2. Follow the same `UPDATE`/`NO_UPDATE` gate and incremental workflow.
3. Run `validate` after a write.

Use the status command when diagnosing setup or map state:

```bash
python3 <skill-dir>/scripts/codebase_map.py status \
  --project-root <project-root>
```

## Understand the lifecycle hook

Lifecycle maintenance is opt-in per project. The plugin does not bundle a
global hook. When the user wants it configured by the plugin, they explicitly
invoke `$setup-codebase-hook` for that project.

The configured lifecycle has one handler:

- `SessionStart` matches `startup|resume|clear|compact`, injects the continuous
  maintenance instruction, includes the current worktree’s concise
  `CODEMAP.md`, and lists initialized submodule map indexes.
- After root-session compaction, `source: compact` delivers the checkpoint to
  the immediate model continuation, which can use its retained conversation
  context directly.

The lifecycle is stateless: `SessionStart` injects context and the Agent updates
map documents directly from verified conversation knowledge at checkpoints.

## Completion criteria

Finish a checkpoint only when all applicable conditions hold:

- the primary task can continue without a map-maintenance detour;
- `CODEMAP.md` remains a concise index rather than a source-code substitute;
- every map document uses one consistent primary natural language, except for
  preserved code identifiers and established technical terms;
- every changed code coordinate uses a real project-relative link and a
  verified symbol where one exists;
- every changed relationship and flow is supported by current source;
- every local link in a Markdown map document resolves, and every Markdown map
  document is reachable from `CODEMAP.md`;
- stale verified content has been corrected; and
- validation reports no errors for every changed worktree.

Keep precise line numbers, commit hashes, unstable statistics, and temporary
task details out of the map.
