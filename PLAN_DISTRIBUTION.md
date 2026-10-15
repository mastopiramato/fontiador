# Fontiador — Plan: packaging, cross-platform distribution and open-source release

Status: proposal (2026-02). Scope: turn a local Windows-only Python app into a signed,
portable, open-source desktop product for Windows, macOS and Linux, with first-class
ingest from Affinity **and** from any other design tool.

---

## 1. What exists today (audit)

| Asset | Reality | Consequence for this plan |
|---|---|---|
| `fontiador_server.py` (2 725 lines) | Single file: HTTP server + embedded HTML/CSS/JS UI + all pipeline logic | Must be split before packaging/CI; UI cannot be linted or translated as-is |
| `fontiador_builder.py` (292 lines) | Clean, dependency-light OTF builder (`fontTools` + `shapely`) | Reusable as-is; becomes the `fontiador.core` package |
| Ingest | Watches `inbox/` for `render_*.png/jpg` (raster grid) and `export_*.json` (vectors) | `export_*.json` is declared but **no producer ships with the repo** — the Affinity script is missing |
| Grid assumption | `RENDER_CELL=1000`, `RENDER_COLS=10`, 103-char `TEMPLATE_CHARS`, baseline at y=800 | Hard-coded template: the #1 blocker for non-Affinity tools |
| Entry point | `python fontiador_server.py`, opens a `pywebview` window, falls back to browser | Only frozen path is `build_exe.bat` → one-file Windows `.exe` |
| `build_exe.bat` | PyInstaller `--onefile --noconsole`, `--collect-all shapely/fontTools/webview/potrace` | Works, but one-file means ~15 s cold start and AV false positives |
| Paths | `BASE_DIR` = exe dir (frozen) or script dir; project data written **next to the binary** | Fails on macOS `.app` (read-only bundle) and on Linux system installs → must move to per-user data dirs |
| Version control | **Not a git repository**; no LICENSE, README, tests, CI | Open-sourcing starts here |
| Python | Dev machine has 3.14; `pywebview` 6.2.1, `shapely` 2.2, `potracer` 0.0.4, `fontTools` 4.66, Pillow 12.3, numpy 2.5 | `potracer` is pure-Python and slow; Shapely wheels exist for all 3 OSes → good portability story |
| i18n | All UI strings and log messages in Spanish, `lang="es"` | Fine as the default locale; must become extractable for a public project |
| No tests | `prueba.txt`, `output/*.otf`, `output/debug/*` are scratch artifacts | Need a fixture corpus + golden tests |

### The three real gaps

1. **No artifact a non-developer can install** on macOS or Linux, and the Windows artifact is an
   unsigned one-file exe that writes state beside itself.
2. **No supported intake from Affinity** (the advertised `export_*.json` producer does not exist),
   and **no intake at all** from Illustrator, Inkscape, Figma, CorelDRAW, FontForge, Glyphs.
3. **No repository, licence, CI, or release process** — nothing to redistribute.

---

## 2. Target architecture

```
fontiador/                      # importable package (the real project)
  __init__.py                # __version__ = single source of truth
  core/
    builder.py               # <- fontiador_builder.py (unchanged logic)
    pipeline.py              # <- import_render / process_inbox / rebuild orchestration
    kerning.py               # <- effective_kerning / set_chars_kerning
    accents.py               # <- compose_accents
    project.py               # <- load/save project + schema migration + paths
  ingest/                    # NEW: the portability layer (see §5)
    base.py                  # SourceAdapter protocol
    grid_raster.py           # current render_*.png path
    svg_per_glyph.py         # NEW: one .svg per glyph from any vector tool
    pdf_page.py              # NEW: single-page PDF sheet (Affinity/Illustrator/Inkscape export)
    affinity_json.py         # NEW: export_*.json contract (+ a real Affinity exporter)
    tool_detect.py           # sniff source from SVG metadata / PDF producer string
  validate/                  # NEW: post-build QA (see §6.5)
  server/
    app.py                   # HTTP routing only
    web/                     # index.html, app.css, app.js, i18n/es.json, i18n/en.json
  cli.py                     # `fontiador build --src ... --out ...` headless mode
  desktop.py                 # pywebview launcher
tests/  fixtures/  docs/  packaging/  .github/workflows/
```

Rationale: `core` and `ingest` stay pure-Python with **no GUI dependency**, so the CLI works in
CI, on a server, and in Docker — while the desktop app is one thin consumer of the same code.

---

## 3. Packaging strategy

### 3.1 Principle: three tiers, not one artifact

| Tier | Artifact | Audience | Effort |
|---|---|---|---|
| A | `pip install fontiador` + `fontiador --browser` | developers, power users, CI | low — do it first |
| B | Native installers: MSI/NSIS, DMG, AppImage + Flatpak + `.deb` | designers (the actual users) | medium |
| C | Portable zip/tarball, no install | shared workstations, locked-down IT | low, reuses B's build |

Every tier is produced from the same git tag by one CI workflow; never hand-build a release.

### 3.2 Windows

- **PyInstaller `--onedir`**, not `--onefile`. One-file unpacks to `%TEMP%\_MEIxxxx` on every
  launch (slow start, and the `BASE_DIR`-next-to-exe assumption breaks). Use
  `--onedir --windowed`, ship the folder.
- Wrap the onedir output in **Inno Setup** (simpler, better LibreOffice/designer ergonomics than
  NSIS) producing `Fontiador-<ver>-win-x64-setup.exe`, per-user install to
  `%LOCALAPPDATA%\Programs\Fontiador` (no admin prompt).
- Register `.fontiadorproj` file association and an "Open in Fontiador" shell verb (see §5.4).
- Optional MSI via WiX only if an enterprise asks; Inno covers 95 % of cases.
- **Code signing**: Azure Trusted Signing (~$10/mo, cheapest path to a real certificate) or an
  OV certificate. Sign both the installer and `Fontiador.exe`. Unsigned builds stay available but
  documented as "SmartScreen will warn".

### 3.3 macOS

- **PyInstaller onedir → `.app` bundle**, then `hdiutil` a DMG with an `/Applications` symlink.
- Build **universal2** (`--target-arch universal2`) so one DMG serves Intel and Apple Silicon.
  Verify `shapely`/`numpy` ship universal2 wheels; if not, build two DMGs (arm64 + x86_64) and
  ship as a single "universal" DMG with both, or move the tracer off Shapely (see §8 risk).
- Bundle metadata in `Info.plist`: `CFBundleIdentifier=io.github.<org>.fontiador`,
  `CFBundleDocumentTypes` for `.fontiadorproj`, `LSMinimumSystemVersion=11.0`.
- **Signing + notarization are mandatory** for a usable DMG: `codesign --deep --options runtime`,
  `xcrun notarytool submit --wait`, then `xcrun stapler staple`. Needs an Apple Developer
  account ($99/yr). Without it, users get "damaged and can't be opened" and the only fix is
  `xattr -dr com.apple.quarantine` — document that fallback in `docs/install-macos.md`.
- **Critical fix before this works**: `PROJECT_FILE`, `OUTPUT` and `fontiador.log` currently live
  beside the executable. Inside a notarized bundle that directory is signed and read-only.
  Move to `~/Library/Application Support/Fontiador/`, `%LOCALAPPDATA%\Fontiador\`,
  `$XDG_DATA_HOME/fontiador/` via a single `paths.py`.

### 3.4 Linux

Ranked by user effort:

1. **AppImage** — one file, `chmod +x`, runs anywhere; the best "portable" story and the one to
   lead with. Build with `appimagetool`; bundle a minimal `libfuse` note for 22.04 users.
   Works with `pywebview`'s GTK/Qt backend — prefer the **Qt (PySide6)** backend, since GTK
   WebKit2 versions diverge wildly across distros.
2. **Flatpak** (flathub) — sandboxed, auto-updating, and the distribution channel designers on
   Linux actually use. Requires a Flathub submission + `org.freedesktop.Sdk` runtime, and forces
   the "inbox watched folder must be a portal-visible directory" fix (see §8).
3. **`.deb` via `fpm`/`nfpm`** — for Debian/Ubuntu users; add a `.rpm` for Fedora the same way.
4. **AUR `PKGBUILD`** — nearly free once the pip tier is clean; a maintainer will usually adopt it.

Ship **both AppImage and Flatpak**; they solve different users and the AppImage doubles as the
"portable" deliverable.

### 3.5 CI/CD (GitHub Actions)

Matrix: `windows-latest`, `macos-14` (arm64), `macos-13` (x86_64), `ubuntu-22.04`
(build on the *oldest* glibc you support).

```
.github/workflows/
  ci.yml          # on PR: ruff + pytest + build a font from fixtures on 3 OSes
  release.yml     # on tag v*: build all artifacts, sign, notarize, publish
  flatpak.yml     # flathub submission automation
```

`release.yml` jobs:
`build-wheels` → `build-win` → `build-mac` (matrix arm64/x86_64) → `build-linux`
(AppImage/deb/rpm) → `flatpak-manifest-pr` → `publish` (attach to GitHub Release + generate
`SHA256SUMS` + `latest.json` manifest for the in-app updater).

Use `softprops/action-gh-release`; keep secrets in `AZURE_*` (Windows signing), `APPLE_ID` /
`APPLE_TEAM_ID` / `APPLE_APP_PASSWORD` (notarization), `GPG_KEY` (Debian repo, later).

Estimated CI cost: ~20 min per release on free public-repo minutes — a fine trade.

### 3.6 Auto-update

Phase 1 (cheap): the app fetches `latest.json` from the GitHub releases API, and if a newer
version exists shows a dismissible banner linking to the download page. No binary patching.
Phase 2 (optional): `tufup` for signed delta updates, or Sparkle/WinSparkle per platform.
Do **not** build a custom updater that downloads and executes binaries without signature
verification.

---

## 4. Deployment & download

- **Primary**: GitHub Releases — `https://github.com/<org>/fontiador/releases/latest`. The README
  and `fontiador.app`-style landing page link straight to `.../releases/latest/download/<name>`,
  which always serves the newest build.
- **Homebrew**: `brew install --cask fontiador` via your own tap, then submit to `homebrew/cask`
  once the DMG is notarized and stable. This is the single highest-leverage macOS channel.
- **winget**: `winget install Fontiador.Fontiador` — a PR to `microsoft/winget-pkgs` per release;
  automate it with `vedantmgoyal9/winget-releaser` in `release.yml`.
- **Flathub** for Linux; `.deb`/`.rpm` attached to the release (later: a signed apt repo).
- **PyPI** as `fontiador` for the developer tier and for `pipx install fontiador`.
- **A plain landing page** (GitHub Pages, single HTML file) with three big download buttons,
  a 60-second GIF of "export → drop → build", and a link to the docs. Designers will not read
  the README; a GIF converts better than any amount of prose.
- **Checksums + provenance**: every release publishes `SHA256SUMS` and, ideally, builds with
  `actions/attest-build-provenance` so anyone can verify the artifact came from this repo's CI.

---

## 5. Ingest: Affinity, and everything else

This is the most important product work. Today the pipeline only understands a *raster sheet on
a fixed 10×1000 px grid*. Make the source layer pluggable.

### 5.1 Define a `SourceAdapter` protocol

```python
class SourceAdapter(Protocol):
    name: str
    def can_handle(self, path: Path) -> bool: ...
    def sniff(self, path: Path) -> SourceInfo: ...      # tool, page size, cell size, baseline
    def to_glyphs(self, path: Path, opts: TraceOptions) -> list[Glyph]: ...
```

`SourceInfo` carries `cell_w, cell_h, cols, rows, baseline_px, upm, tool, order` — so the
hard-coded `TEMPLATE_CHARS`/1000 px constants become **per-source configuration with a sane
default**, and a user can import their own layout.

### 5.2 Adapters to ship

| Adapter | Input | Notes |
|---|---|---|
| `grid_raster` | the current `render_*.png` sheet | already implemented; make grid geometry configurable |
| `svg_sheet` | one SVG containing all glyphs on a grid | parse with `svgpathtools` or `fontTools.svgLib.path`; **no tracing → sharper outlines** |
| `svg_per_glyph` | `A.svg, B.svg, …` in a folder/zip | **the universal route**: every design tool exports SVG |
| `pdf_sheet` | one-page PDF (Affinity/Illustrator/Inkscape/CorelDRAW export) | `pdf2image`+`pypdfium2` to vector paths, or rasterize at 600 dpi and reuse the tracer |
| `affinity_json` | `export_*.json` | the existing, best-quality contract — needs a real exporter (§5.3) |
| `ufo` / `designspace` | FontForge/Glyphs/RoboFont | import an existing UFO for *editing* rather than authoring; scope creep — park it |
| `image_folder` | `A.png …` (scanned/hand-drawn, FontLab-style) | raster per glyph; trivially reuses `trace_mask` |

**Vector beats raster, always.** The current raster+trace pipeline loses curve fidelity and
produces 11 000+ kerning pairs from noisy edges. Prefer `svg_sheet`/`affinity_json` in the docs,
keep raster as the fallback for tools that cannot export vectors.

### 5.3 The Affinity story (fix the missing half)

The repo advertises an Affinity script `"Fontiador: exportar glifos"` that writes `export_*.json`,
but it is not in the tree. Ship it, properly:

1. **`integrations/affinity/fontiador-export.js`** — an Affinity Designer/Photo 2 **JavaScript
   script** (`Document > Scripts`, or `~/Library/Application Support/Affinity Designer 2/
   Scripts/`). It walks the artboard, slices cells, converts each curve to `M/L/C/Z` commands in
   document coordinates, and writes one `export_<timestamp>.json` into the watched inbox.
   This is the highest-fidelity path and the one to feature in marketing.
2. **A template document** (`docs/affinity/Fontiador-Template-v6.afdesign`) matching
   `TEMPLATE_CHARS` — the contract currently exists only as a Python list.
3. **A changelog note** in the script: when `TEMPLATE_CHARS` changes, the template version must
   bump, and the app must refuse mismatched template versions with a *clear* message instead of
   silently importing the wrong glyph into the wrong slot.
4. **Documented manual fallback**: export one PNG at 600 dpi, name it `render_<anything>.png`,
   drop it in the inbox. This is what users actually do today — make it first-class.

### 5.4 Non-Affinity design software

The message to the public: *Fontiador does not require Affinity.* Anything that can produce a
vector or raster sheet works.

- **Illustrator / Inkscape / CorelDRAW / Figma**: "export one SVG (or one PNG at 600 dpi) using
  the Fontiador template grid, name it `render_*.svg` / `render_*.png`".
- **Figma**: add a small plugin (`integrations/figma/manifest.json`) that exports the selection
  as per-glyph SVGs into a folder — Figma plugin API is JavaScript, so this is a weekend job and
  a big reach win.
- **Inkscape**: ship a batch export extension (`integrations/inkscape/fontiador_export.inx/.py`)
  that slices a grid layer into `A.svg, B.svg, …` — Inkscape extensions are plain Python and can
  literally import `fontiador.ingest`.
- **Glyphs / FontForge / RoboFont**: these already are font editors; the honest answer in the
  docs is "you probably don't need Fontiador, but you can export SVG from Glyphs and use us as a
  kerning/tracing front-end".
- **A generic "Open from folder…" and "Open file…" button in the UI.** Right now the only entry
  is a watched `inbox/`. Drag-and-drop onto the window (`pywebview` supports
  `window.events.loaded` + drag-drop handlers) plus a native file picker removes the single
  biggest usability complaint and makes the tool feel like an app, not a service.
- **Stable JSON contract**, versioned and documented in `docs/format-export-json.md`, so anyone
  can write an exporter for their tool. Add `"format": "fontiador-export", "version": 1` to every
  payload and validate it on import.

---

## 6. Product work needed to make it distributable

### 6.1 Data locations (blocker for macOS/Linux)
`paths.py` with `platformdirs`:
- data: `~/Library/Application Support/Fontiador`, `%LOCALAPPDATA%\Fontiador`, `~/.local/share/fontiador`
- config: same family, separate `config/`
- **plus** a "portable mode": if a file `portable.flag` (or `FONTIADOR_PORTABLE=1`) sits next to the
  executable, keep everything beside it. This preserves today's behaviour for USB-stick users and
  satisfies the "portable" requirement without breaking sandboxed installs.

### 6.2 Split the monolith
Move the `PAGE = r"""…"""` string (lines 844–2444) into `server/web/`. Benefits: real HTML/CSS/JS
with syntax highlighting and linting, cacheable static assets, translatable strings, and a UI
that can be worked on without touching Python. Do this **before** packaging; it is mechanical and
de-risks everything else.

### 6.3 Dependency hygiene
- Split `requirements.txt` into `dependencies` (runtime) and `[project.optional-dependencies]`
  (`desktop = pywebview`, `dev = pytest/ruff`, `vector = svgpathtools/pypdfium2`).
- Pin with a lockfile (`uv.lock` or `pip-compile`) and add Dependabot.
- `potracer` is pure Python and slow on a 103-cell sheet. Consider `pypotrace` (needs C build →
  bad for wheels) or call `potrace`/`autotrace` as an external optional binary, keeping
  `potracer` as the bundled fallback. Benchmark before committing.
- Replace `shapely` tracing-only usage gradually with `fontTools` pens where possible: Shapely is
  the largest and most fragile dependency in the bundle, and dropping it would shrink the
  installer substantially.

### 6.4 Robustness
- Port collision: `--port 8765` is hard-coded; pick a free ephemeral port and pass the URL to the
  webview. Also bind-loopback only (already done) and add a random per-session token to the URL
  so a local browser tab cannot drive the API.
- Long builds currently run inline in a request handler; move to a worker with progress
  (the `JOB` dict already exists — formalize it as an SSE endpoint).
- Crash reporting: local log file by default, **opt-in** `sentry-sdk` or a "copy diagnostics"
  button. Never auto-upload.

### 6.5 Validation — the feature that earns trust
A designer's worst outcome is shipping a broken font. Add `fontiador validate`:
- `fontTools.ttLib` round-trip + `fontTools.varLib`-free sanity: cmap coverage vs requested
  charsets, missing-glyph report, advance/baseline checks, contour direction, self-intersections.
- Render a proof sheet (all glyphs + a paragraph, via `freetype-py` or HTML→PNG) into
  `output/proof.png` and show it in the UI before export.
- `ots-sanitize` (bundle the binary where possible) for the strict OpenType check.
- Export **multiple formats from the same project**: `.otf` (CFF, current), `.ttf` (glyf —
  `cu2qu`), `.woff2` (web) and `.ttx` for debugging. Web fonts are a large part of the real
  market for a tool like this.
- Store the whole project as a portable `.fontiadorproj` (zip: JSON + source renders + thumbnails)
  so a user can back it up, share it, or open it on another OS. This is also what the file
  association in §3.2/§3.3 should point to.

### 6.6 Tests and fixtures
- `fixtures/` with three tiny fonts: a 6-glyph smoke sheet, a full sheet, and a malformed one.
- Golden tests on OTF output: compare `ttx` dumps of key tables (cmap, hmtx, kern/GPOS) so
  refactors cannot silently change metrics.
- A pytest that runs `import_render` → `rebuild` end-to-end on Linux in CI — this catches the
  platform path bugs early.

---

## 7. Open-source readiness

| Item | Action |
|---|---|
| **Licence** | `AGPL-3.0-or-later` or `GPL-3.0-or-later` if you want derivatives to stay open; `MIT` if you want maximum adoption (plugins, forks, commercial use). For a designer tool, **MIT/Apache-2.0 maximizes reach**; AGPL protects against a closed hosted fork. Pick consciously and put it in `LICENSE` + `pyproject.toml`. |
| **Repo** | `git init`, `.gitignore` (`__pycache__`, `*.pyc`, `output/`, `inbox/`, `dist/`, `build/`, `fontiador.log`, `fontiador_project.json`, `*.otf`), branch protection on `main`, PR template. |
| **Community files** | `README.md` (GIF first, install matrix second, architecture last), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant), `SECURITY.md`, `CHANGELOG.md` (Keep a Changelog + SemVer), `docs/`. |
| **Translations** | UI is Spanish-only. Extract strings to `i18n/es.json` + `en.json`, add a language switch, and let the community add locales. English README + a bilingual UI is the difference between 200 and 20 000 users. |
| **Branding/legal** | Do **not** use "Affinity" in the product name or logo; "Fontiador" is fine, but keep the Affinity integration described as "a script for Affinity Designer" and add a trademark disclaimer. Verify the name is free on PyPI/GitHub and not a registered mark. |
| **Accessibility & UX** | The kerning workflow has heavy keyboard semantics (arrows/Shift/Ctrl+Enter/Esc, lock buttons). Document them in-app (a "?" overlay) — keyboard-first is a genuine differentiator versus clicking in Affinity. |
| **Funding/roadmap** | A public roadmap (GitHub Projects or a `ROADMAP.md`), "good first issue" labels, and a docs site. If you accept money, GitHub Sponsors + Open Collective, with a documented governance model before anyone depends on it commercially. |
| **Anti-features** | No telemetry by default, no account, no cloud, no licence server. "Local, offline, your files stay yours" is a selling point; write it down as a policy so it cannot drift. |

---

## 8. Risks and open questions

1. **`pywebview` on Linux** is the shakiest dependency (GTK vs Qt vs distro webkit versions).
   Mitigation: default to the Qt/PySide6 backend in the Flatpak/AppImage, keep `--browser`
   fallback as a supported mode, and consider Tauri/Wails later *only* if pywebview becomes a
   support burden — the server/UI split from §6.2 makes that migration cheap.
2. **Signing costs/identity**: ~$99/yr Apple + ~$120/yr (or Azure Trusted Signing) Windows is a
   real commitment. Decide before promising one-click installs; until then, publish clearly
   labelled unsigned builds with per-platform "how to open it" instructions.
3. **Shapely/numpy wheel coverage** on the macOS universal2 and musl/Alpine targets — verify
   early; if it fails, ship separate arch DMGs (already the fallback in §3.3).
4. **Template drift**: `TEMPLATE_CHARS` ↔ template document ↔ exporter script are three copies of
   one contract. Version the template (`template_version` in the JSON) and fail loudly.
5. **Scope creep into a font editor**: the pull toward UFO/Glyphs import, OpenType feature
   authoring, variable fonts is strong. The wedge is *"affordable tracing + kerning for fonts
   drawn in a vector tool"* — protect it.
6. **Performance**: a full sheet trace is minutes on `potracer`. Users will assume it hung. Real
   progress reporting (§6.4) plus a per-cell preview is mandatory before a public 1.0.

---

## 9. Phased roadmap

| Phase | Deliverable | Key work | Exit criterion |
|---|---|---|---|
| **0. Groundwork** (1–2 wk) | Repo + tier A | `git init`, licence, split monolith, `paths.py`, `pyproject.toml`, `pipx install fontiador` works, CI runs tests on 3 OSes | `fontiador` installs and builds a font from a fixture on Windows/macOS/Linux |
| **1. Real app** (2–4 wk) | Usable native app | `--onedir` PyInstaller, Inno Setup, DMG, AppImage; in-app file picker + drag-drop; progress + validation/proof sheet; `.fontiadorproj`; `.otf/.ttf/.woff2` export | A designer on each OS downloads one file, imports a sheet, exports a font |
| **2. Sources** (2–4 wk) | Multi-tool ingest | `SourceAdapter`, `svg_sheet` + `svg_per_glyph` + `pdf_sheet`, the real Affinity exporter + template, versioned JSON contract, docs per tool | Affinity, Illustrator, Inkscape and Figma each documented end-to-end and tested |
| **3. Public release** (2 wk) | 1.0 | Signing + notarization, Homebrew cask, winget, Flathub, landing page with GIF, EN/ES UI, README/CONTRIBUTING/SECURITY, CHANGELOG, release automation | `v1.0.0` published, four install channels live, a stranger installs it unaided |
| **4. Ecosystem** (ongoing) | Growth | Figma plugin, Inkscape extension, community locales, auto-update, apt repo, proof-sheet templates | External contributors shipping adapters without core changes |

**Recommended first three commits** (all low-risk, unblock everything else):
1. `git init` + `.gitignore` + `LICENSE` + `README.md` (with a recorded GIF).
2. Split `fontiador_server.py` into `fontiador/` package with `paths.py` (platformdirs + portable flag)
   and the web assets extracted — no behaviour change, verified by one end-to-end test.
3. `pyproject.toml` + `ci.yml` running `ruff`, `pytest`, and a real font build on the 3-OS matrix.

---

## 10. Immediate answers to the three questions asked

- **"An executable installer, portable for Linux, macOS and Windows"** → `--onedir` PyInstaller
  per OS, wrapped as Inno Setup (Windows), notarized DMG universal2 (macOS), AppImage + Flatpak +
  `.deb` (Linux), all produced by one tag-driven GitHub Actions workflow, with a `portable.flag`
  mode for genuine no-install portability. Tier A (`pipx install fontiador`) ships immediately and
  is the same code.
- **"Deploying, downloading, exporting via Affinity"** → GitHub Releases as the source of truth,
  then Homebrew/winget/Flathub/PyPI for discovery; the missing Affinity exporter JavaScript plus
  a matching `.afdesign` template must be written and versioned, and the raster fallback made
  first-class.
- **"Exporting font images via other design software"** → a pluggable `SourceAdapter` layer with
  SVG-per-glyph and PDF-sheet adapters as the universal route, a versioned public JSON contract
  so anyone can write their own exporter, and drop-in plugin/extension skeletons for Figma and
  Inkscape.
- **"Open source with the public"** → choose the licence deliberately (MIT for reach, AGPL for
  protection), ship the community files, translate the UI to English, never put "Affinity" in the
  product name, and keep the roadmap and governance public from day one.
