# Harness reference

The evidence base each harness backend is written against (REQ-06, D-04).
Backends must resolve exactly the directories recorded here; change this
document first, then the backend.

Each entry records four fields: **Skill directories per scope** (the single
backticked path per scope line is the backend's install target), **Discovery /
precedence**, **Official docs**, and **Local source checkout**. Source
checkouts live in the gitignored `checkouts/` directory at the repo root;
each entry records the clone command and the commit the entry was verified
against.

## Claude Code

- **Skill directories per scope:**
  - user: `~/.claude/skills/`
  - project: `.claude/skills/`
- **Discovery / precedence:** Each skill is a subdirectory containing
  `SKILL.md` (agentskills.io frontmatter). Claude Code loads personal
  (user-scope) skills, project skills, and plugin-provided skills; skill
  names surface to the model via the Skill tool. Project and personal skills
  with the same name collide — project scope is the more specific and wins
  in practice; plugin skills are namespaced (`plugin:skill`). Nested
  directories under `skills/` are not skills; only direct subdirectories
  with a `SKILL.md` are discovered.
- **Official docs:**
  - https://code.claude.com/docs/en/skills
  - https://agentskills.io/specification (Claude Code is the reference
    client for the spec)
- **Local source checkout:** none possible — Claude Code is closed source.
  Local evidence is the installed bundle at
  `~/.local/share/claude/versions/<version>/` (2.1.206 at verification
  time, 2026-07-10) plus the official docs above.

## pi

- **Skill directories per scope:**
  - user: `~/.pi/agent/skills/`
  - project: `.pi/skills/`
- **Discovery / precedence:** Auto-discovery in `package-manager.ts`
  (`addAutoDiscoveredResources`): project skills load from `.pi/skills/`
  and from any ancestor `.agents/skills/` directories, then user skills
  from `~/.pi/agent/skills/` and `~/.agents/skills/` — project entries are
  registered before user entries. `CONFIG_DIR_NAME` is `.pi`
  (`src/config.ts:443`); the user agent dir is `~/.pi/agent/`
  (`src/config.ts:474`). Explicit `skills` arrays in pi settings
  (user or project `settings.json`) enable/disable discovered entries.
  The shared cross-agent dirs (`~/.agents/skills/`, ancestor
  `.agents/skills/`) are also read, but the pi-native paths above are the
  backend's install targets.
- **Official docs:**
  - https://github.com/earendil-works/pi
  - https://agentskills.io (pi is on the official client list)
- **Local source checkout:** `checkouts/pi`
  (`git clone --depth 1 https://github.com/earendil-works/pi.git checkouts/pi`);
  verified at commit `bc469b0` (2026-07-10). A full working checkout also
  lives at `~/AI/pi`. Evidence files:
  `packages/coding-agent/src/config.ts`,
  `packages/coding-agent/src/core/package-manager.ts` (lines ~2196-2306).

## Hermes

- **Skill directories per scope:**
  - user: `~/.hermes/skills/`
  - project: `.hermes/skills/`
- **Discovery / precedence:** Hermes is our own harness; **this entry is
  the normative contract, defined here** (D-03) — Hermes implements what
  this document records, not the other way around. Contract: every direct
  subdirectory of a skills dir containing a `SKILL.md` with agentskills.io
  frontmatter (name equal to the directory name, description present) is a
  skill; both scopes are supported; on a name collision the project scope
  shadows the user scope; symlinked skill directories are not followed.
- **Official docs:** none public — this section is the normative
  specification of Hermes skill support until Hermes ships public docs.
- **Local source checkout:** not present on this machine at verification
  time (2026-07-10). When a Hermes checkout exists it goes at
  `checkouts/hermes`; until then this contract section is the evidence.

## opencode

- **Skill directories per scope:**
  - user: `~/.config/opencode/skills/`
  - project: `.opencode/skills/`
- **Discovery / precedence:** `packages/opencode/src/skill/index.ts`
  discovers skills by globbing `{skill,skills}/**/SKILL.md` inside every
  config directory — the XDG global config dir `~/.config/opencode/`
  (xdg-basedir, `packages/core/src/global.ts`), ancestor `.opencode/`
  directories from cwd up to the worktree root, and `~/.opencode`
  (`packages/opencode/src/config/paths.ts`). Both `skill/` and `skills/`
  subdirectory names are accepted; we install to `skills/`. Unless
  disabled by flags, opencode additionally reads external dirs with
  pattern `skills/**/SKILL.md`: `~/.claude/skills/`, `~/.agents/skills/`,
  and ancestor project `.claude/`/`.agents/` dirs. Extra locations can be
  added via `skills.paths`/`skills.urls` in `opencode.json`. Duplicate
  skill names: the later-discovered one overwrites with a logged warning;
  the built-in `customize-opencode` skill registers first so any on-disk
  skill overrides it.
- **Official docs:**
  - https://opencode.ai/docs/skills/
  - https://agentskills.io (opencode is on the official client list)
- **Local source checkout:** `checkouts/opencode`
  (`git clone --depth 1 https://github.com/sst/opencode checkouts/opencode`);
  verified at commit `1c7f65f` (2026-07-10). Evidence files:
  `packages/opencode/src/skill/index.ts`,
  `packages/opencode/src/config/paths.ts`,
  `packages/core/src/global.ts`.
