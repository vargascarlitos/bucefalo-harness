List each ticket — one per line — using this format:

  [layer] Title | 1-4 | estimate | one-line description

- **layer**: a free token for the part of the system this ticket targets (e.g. `api`,
  `web`, `shared`, `infra` — whatever layers your project uses). It becomes the chunk
  sub-directory the spec is written to.
- **1-4** (MoSCoW priority): 1=Must Have, 2=Should Have, 3=Could Have, 4=Won't Have
- **estimate**: free text, e.g. `1-2 Hrs`, `2-4 Hrs`, `4-8 Hrs`, `1-2 Days`

Example:

  [api] Amenity filter endpoint | 2 | 2-4 Hrs | filter listings by amenity query param
  [web] Amenity filter chips    | 3 | 2-4 Hrs | UI chips that drive the filter endpoint
