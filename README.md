# Plantilla de Harness para Claude Code — edición ClickUp

Un "harness" portable y agnóstico del stack para Claude Code (workflow de SDLC asistido por IA)
conectado a **ClickUp vía el ClickUp MCP**.

Esta plantilla es **agnóstica del stack** en la capa de orquestación (Capa 1) y en la
integración con ClickUp (Capa 2). La capa específica del producto/stack (Capa 3 — reglas
de código, los comandos del gate de `implement`/`verify`, los specialists del code review) viene con
placeholders que vas completando una vez que conocés el stack de tu proyecto.

## Las tres capas

| Capa | Qué | Estado en esta plantilla |
|-------|------|--------------------------|
| 1. Cerebro de orquestación | Los skills de SDLC + helpers de `_shared` + formato `specs/` + hooks | Portado, listo |
| 2. Integración con herramienta de PM | Llamadas a ClickUp vía MCP, centralizadas en `_shared/pm-clickup.md` | Portado, listo |
| 3. Producto/stack | `CLAUDE.md`, `.claude/rules/`, comandos del gate de verify, specialists de review | Placeholders — completar por proyecto |

## Cómo funciona la integración con PM

Se accede a ClickUp a través del **ClickUp MCP** (un connector de claude.ai a nivel de cuenta), así que
los skills llaman directamente a las tools del MCP — no hay CLI de PM, ni cache local, ni API key en la
config. Todo el acoplamiento con el PM está centralizado en un solo archivo:
`.claude/skills/_shared/pm-clickup.md` (operación lógica → tool del MCP + mapa de estados). Cambiá
ese único archivo para reapuntar a otra herramienta de PM.

## Prerrequisitos

1. **ClickUp MCP conectado** en tu sesión de Claude Code (connector de claude.ai).
   Verificá con una llamada de lectura como `clickup_get_workspace_hierarchy`.
2. Una **List** de ClickUp de destino para los tickets de tu proyecto.

## Configuración inicial de ClickUp (manual — el MCP no puede hacer esto)

El ClickUp MCP puede crear tasks/comments/docs pero **no puede crear statuses personalizados**
ni habilitar Task IDs personalizados. Hacé esto en la UI de ClickUp:

1. **Statuses.** En tu List de destino (o su Space), configurá estos 7 statuses para reflejar
   la máquina de estados del workflow (List settings → Statuses):

   ```
   Todo → In Progress → In Review → Dev Done → QA → QA Reject → Done
   ```

   Mapeo de tipos: `Todo` = not started; `In Progress`/`In Review`/`Dev Done`/`QA`/`QA Reject`
   = active/custom; `Done` = done/closed.

2. **(Opcional) Task IDs personalizados.** Habilitá el ClickApp *Task IDs* y poné un prefijo por Space
   (ej. `TASK`) para que las tasks tengan IDs legibles como `TASK-42`. Si lo hacés, poné
   `clickup.use_custom_task_ids: true` en `.claude/workflow.json`. Si no, el harness usa
   los task IDs nativos de ClickUp.

## Configurar el harness

Editá `.claude/workflow.json`:

- `project_name` — el nombre de tu proyecto
- `id_prefix` — prefijo de ticket para los nombres de archivo de los specs locales (ej. `TASK` → `TASK-0042-slug.md`)
- `clickup.workspace_id` / `space_id` / `list_id` — tus IDs de destino
  (resolvelos con `clickup_get_workspace_hierarchy` o `clickup_get_list`)
- `clickup.states` — cambiá solo los valores de la derecha si tus statuses de ClickUp difieren
  de los nombres canónicos

> Los valores que vienen acá apuntan a la list **"List"** (`901114014067`) en el Space dedicado
> **"harness-clickUp"** (`90114195110`), que tiene los 7 statuses del harness configurados
> y se usa para validar el port. Cambialos para un proyecto real.

**No hay `.claude/workflow.local.json`** — la identidad del usuario viene del
MCP (`clickup_get_workspace_members` / `clickup_resolve_assignees`).

## El core loop (qué incluye)

```
/create-ticket   → crea la task de ClickUp + el spec local del work-item
/ticket-review   → gate de readiness (mecánico + semántico + cross-layer)
/start-ticket    → gate, branch, despacha el implement agent, status → In Progress
/complete-dev    → despacha el verify agent; pasa → In Review (+ link de MR + comment), falla → In Progress
/pr-review       → code review; aprueba → Dev Done, cambios → In Progress
/review-outcome  → resultado de QA; pasa → Done, falla → QA Reject
```

También se incluye: un **CI review-agent** para **GitHub Actions** — agnóstico del stack, corre tres
specialists (correctness / security / tests) en cada PR y emite un review de approve / request-changes.
Ver `.github/workflows/review-agent.yml` y
[`.claude/agents/review-agent/`](.claude/agents/review-agent/README.md).

También se incluye (más allá del core loop):
- **Autoría de chunks:** `/create-chunk` (scaffolding de una feature + sus tickets), `/update-plan`.
- **Pipeline de feedback:** `/feedback` (registra una observación), `/ai-insights` (agrega los
  workflow records en un reporte), `/improve-agents` (agrupa patrones → ediciones de bajo riesgo al harness → PR de GitHub).
- **`/mutation-tests`** — orquestador de mutation-testing (la tool + los comandos son placeholders del proyecto).

Lo único que queda por completar por proyecto es la **Capa 3** (reglas del stack en `.claude/rules/`, los
comandos del gate de verify/implement, y las particularidades del stack del review-agent).

## Completar la Capa 3 (cuando ya conocés tu stack)

1. Escribí `CLAUDE.md` a partir de `CLAUDE.md.template` (overview del proyecto, comandos, arquitectura).
2. Agregá `.claude/rules/*.md` con convenciones de código path-scoped para tu stack.
3. Completá los comandos del gate en `.claude/agents/verify/system-prompt.md`
   (`{{TEST_CMD}}`, `{{LINT_CMD}}`, `{{TYPECHECK_CMD}}`, `{{FORMAT_CMD}}`).
4. Completá los idioms de build/test en `.claude/agents/implement/system-prompt.md`.

## Estructura de directorios

```
.claude/
├── settings.json              # hooks + permisos (sin plugin de PM — ClickUp es un MCP)
├── workflow.json              # config del proyecto + ClickUp
├── skills/
│   ├── _shared/
│   │   ├── pm-clickup.md       # ★ todo el acoplamiento con PM: op lógica → tool del MCP + mapa de estados
│   │   ├── load-config.md
│   │   └── find-work-item.md   # resolución vía clickup_search/filter
│   ├── create-ticket/
│   ├── ticket-review/
│   ├── start-ticket/
│   ├── complete-dev/
│   ├── pr-review/
│   └── review-outcome/
├── agents/
│   ├── implement/             # agnóstico del stack, placeholders del gate
│   └── verify/                # agnóstico del stack, placeholders del gate
└── hooks/
    ├── audit-docs-hook.sh
    └── audit-docs.sh
specs/
├── work-items/_template.md
├── chunks/
└── plans/
```
