# Tutorial — el harness de punta a punta (con un ejemplo)

Este es un paso a paso del **core loop** completo, siguiendo un ticket de ejemplo desde que
se crea hasta que queda en `Done`. La idea es que veas **qué escribís vos**, **qué te
pregunta cada skill** y **cómo cambia el estado del ticket en ClickUp** en cada etapa.

> Si todavía no configuraste el harness (ClickUp MCP conectado + `.claude/workflow.json`
> apuntando a tu List), arrancá por el [`README.md`](README.md). Este tutorial asume que ya
> está todo conectado.

## El ticket de ejemplo

Vamos a construir una feature chica y concreta:

> **Buscar productos por nombre** — un input de búsqueda en la página de productos que filtra
> la lista a medida que el comprador escribe.

## El mapa del recorrido

Cada skill empuja el ticket por la máquina de estados. Este es el camino feliz:

```
/create-ticket   →  Todo
/ticket-review   →  (Todo)        gate: ¿está listo para que la IA lo construya?
/start-ticket    →  In Progress   gate + branch + dispatch del implement agent
/complete-dev    →  In Review     verify pasa → push + MR
  (CI review-agent corre solo en el PR)
/pr-review       →  Dev Done      code review humano aprueba
/review-outcome  →  Done          QA aprueba
```

Y las dos ramas de "algo salió mal":

```
/complete-dev    verify falla     →  vuelve a In Progress (no hay push ni MR)
/pr-review       changes requested →  vuelve a In Progress
/review-outcome  rejected          →  QA Reject
```

---

## Paso 1 — `/create-ticket`: crear el ticket

Escribís el comando:

```
/create-ticket
```

El skill te va a hacer preguntas por tandas (vía `AskUserQuestion`). Para nuestro ejemplo:

| Pregunta | Lo que respondés |
| --- | --- |
| **Title** | `Buscar productos por nombre` |
| **Area** | `Frontend / Full stack` |
| **Priority** (MoSCoW) | `2 - Should Have` |
| **Estimate** | `2-4 Hrs` |
| **User story** | `Como comprador, quiero buscar productos por nombre para encontrar lo que busco sin recorrer toda la lista.` |
| **Design ref** | `Yes` → frame `Products – Search`, URL del diseño, node `1024:512` |

Después junta los **Acceptance Criteria** de a uno (Given/When/Then). El skill **exige al
menos un Happy Path** antes de dejarte cerrar:

- **Happy path:** Given hay productos cargados, When escribo `café` en el buscador, Then la
  lista muestra solo los productos cuyo nombre contiene `café`.
- **Validation:** Given el buscador tiene texto, When borro todo, Then vuelven a mostrarse
  todos los productos.
- **Edge case:** Given ningún producto coincide, When busco `xyz123`, Then se muestra un
  estado vacío "Sin resultados".

Luego los **Edge Cases & Error States**:

> Estado loading mientras responde el backend; error de red → toast "No se pudo buscar";
> la búsqueda es case-insensitive y tolera acentos.

Y el **Scope** (in / out / dependencies):

- **In scope:** el input de búsqueda en la página de productos; filtrado por el query param `q`.
- **Out of scope:** filtros por categoría o precio; tolerancia a errores de tipeo.
- **Dependencies:** Consumes: `GET /api/products` (existing). Provides: `GET /api/products?q=` (new).

### Qué hace el skill con eso

1. Mapea la prioridad MoSCoW a la prioridad de ClickUp (`2 - Should Have` → `high`).
2. Calcula un **prefijo de título** según lo que cargaste. Como diste ACs **y** un design ref,
   no lleva prefijo. (Si te faltaba el diseño quedaría `Missing Design: `; si no había ni
   diseño ni ACs, `Draft: `.)
3. Crea la task en ClickUp con status `Todo` (vía `op: create-task`), y te devuelve el `id` y
   la `url`.
4. Escribe el **spec local**, que es la **fuente de verdad** del cuerpo del ticket:

```
✓ Created TASK-42 — "Buscar productos por nombre" in ClickUp
  https://app.clickup.com/t/...
✓ Work item spec written: specs/work-items/TASK-0042-buscar-productos-por-nombre.md

Ready to start? Run /ticket-review TASK-42 to check readiness, or /start-ticket TASK-42 to begin work.
```

El archivo `specs/work-items/TASK-0042-buscar-productos-por-nombre.md` queda con frontmatter
YAML (`state: Todo`, `priority`, `estimate`, `clickup_id`, `clickup_url`…) y las secciones
`## User Story`, `## Acceptance Criteria`, `## Edge Cases & Error States`, `## Scope`,
`## Design Reference`.

> **Importante:** esos encabezados están en inglés a propósito. El gate del Paso 2 los parsea
> de forma literal — son tokens funcionales, no prosa.

---

## Paso 2 — `/ticket-review`: el gate de readiness

```
/ticket-review TASK-42
```

Este es el **portero**: decide si el ticket está lo bastante claro como para que la IA lo
construya sin adivinar. Corre tres fases:

- **Fase A — chequeos mecánicos** (`check_mechanical.py`, determinístico): que estén todas las
  secciones requeridas y no vacías, que los links de diseño sean usables, que `clickup_id`
  coincida, y que `estimate` y `priority` estén cargados.
- **Fase B — chequeo semántico** (una pasada del LLM con un rubric): ¿el comportamiento es
  inequívoco? ¿cada AC es **testeable** (nada de "tiene que andar bien")? ¿el título y la user
  story hablan de lo mismo? ¿el spec local coincide con la descripción en ClickUp?
- **Fase C — auditoría cross-layer** (`check_crosslayer.py`): si el ticket **consume** un
  contrato (`Consumes:`) que ningún ticket hermano del mismo chunk **provee** (`Provides:`),
  lo marca. En nuestro caso el `Consumes: GET /api/products` está anotado `(existing)`, así
  que pasa.

Si las tres dan verde:

```
READY: TASK-42 passed all gates.
```

### ¿Y si el gate encuentra un hueco?

Supongamos que en la Fase B un AC quedó vago ("Then la búsqueda funciona"). El skill abre un
**loop de expansión interactivo**, de a un hueco por vez:

```
Gap: [ac-quality] El AC "Then la búsqueda funciona" no es observable.
Propuesta: "Then la lista muestra solo los productos cuyo nombre contiene el texto buscado."

  ( ) Accept proposal   ( ) Edit   ( ) Skip (will fail gate)
```

Cuando aceptás o editás, el skill **reescribe el spec local y la descripción en ClickUp** (las
mantiene sincronizadas) y vuelve a correr el gate hasta que da `Ready` o cancelás. Hay un
`--force` para saltearlo, pero deja un comment auditable en la task.

> El estado del ticket sigue en `Todo` durante este paso — el gate todavía no arranca trabajo,
> solo valida.

---

## Paso 3 — `/start-ticket`: arrancar el trabajo

```
/start-ticket TASK-42
```

Acá empieza el trabajo de verdad. El skill, en orden:

1. **Barre worktrees** que hayan quedado de corridas interrumpidas.
2. **Corre el gate** del Paso 2 (`/ticket-review`). Si da `Not Ready` y no querés refinar,
   **corta acá** — no se crea ninguna branch.
3. Muestra el resumen del ticket y, si ya está más allá de `Todo`, te avisa antes de tocar nada.
4. **Pasa el status a `In Progress`** en ClickUp (`op: set-status`).
5. **Sincroniza con `main`** (`git fetch` + `git merge origin/main`) y **crea la branch**. Te
   pregunta el tipo (`feat` / `fix` / `chore` / `docs` / `refactor`) y arma el nombre:

   ```
   feat/task-42-buscar-productos-por-nombre
   ```

6. Actualiza el spec local (`state: In Progress`, `start_date`, `branch:`).
7. **Despacha el `implement` agent** en un worktree aislado. El agent trabaja la lista de ACs
   con TDD, respetando las reglas de `.claude/rules/` que apliquen a los archivos que toca.
8. Encadena al Paso 4 automáticamente.

```
✓ Implement complete for TASK-42
  Branch: feat/task-42-buscar-productos-por-nombre

Next: invoke /complete-dev TASK-42 to run the gates, create the MR, and route the ticket.
```

> En esta plantilla el `implement` agent es **agnóstico del stack**: sus comandos de build/test
> son placeholders de la **Capa 3** que completás por proyecto.

---

## Paso 4 — `/complete-dev`: validar y abrir el MR

```
/complete-dev TASK-42
```

Cierra el desarrollo validando de forma **determinística**:

1. Resuelve la branch (si estás en `main`/`master`, **corta** — algo anda mal).
2. **Despacha el `verify` agent**, que corre los gates del proyecto (test / lint / typecheck /
   format + cobertura de ACs). El verify **no arregla nada**: reporta con precisión `file:line`
   y devuelve un JSON `{ status: "pass" | "fail", gates: [...] }`.
3. **Ramifica según el resultado:**

**Si `verify` pasa** → commit (staging seguro: **nunca** `git add -A`, para no barrer secretos),
push, crea el **MR** (`glab` en GitLab o `gh` en GitHub), lo linkea a la task, pasa el ticket a
**`In Review`** y postea un workflow record `dev-complete` como comment.

```
✓ Verify passed
✓ MR !42 created: https://...
✓ TASK-42 moved to IN_REVIEW

Next: a code reviewer can run /pr-review on MR !42.
```

**Si `verify` falla** → **no** hay commit, push ni MR. El ticket **vuelve a `In Progress`** y te
imprime las fallas para que las arregles y vuelvas a correr `/complete-dev`:

```
VERIFY FAILED — fix and re-run /complete-dev:
  [tests] src/search.test.ts:21: expected empty state on no matches
```

---

## Paso 4.5 — el CI review-agent (automático)

Apenas se abre el PR, el **CI review-agent** (GitHub Actions,
`.github/workflows/review-agent.yml`) corre **solo**, sin que escribas nada. Lanza tres
specialists en paralelo — **correctness**, **security**, **tests** — y deja un review de
`approve` / `request-changes` con un bloque `review-agent-findings` en JSON. Es la red de
seguridad automática que corre **antes** del review humano del Paso 5.

---

## Paso 5 — `/pr-review`: code review humano

Lo corre **otra persona** (el reviewer), no quien programó:

```
/pr-review TASK-42
```

El skill verifica que tengas `glab`/`gh` autenticado, encuentra el MR/PR abierto de la branch,
y te muestra el resumen (diff, estado del pipeline de CI, cantidad de archivos). Después junta
los hallazgos del review por tandas: correctness, logic errors, patterns, test coverage, rondas
de cambios y el **veredicto** final.

Con eso:

- Postea un record `code-review` (JSON) como comment en ClickUp **y** un resumen legible en el MR.
- **Ramifica por veredicto:**
  - **Aprobado** (cualquier variante) → ticket a **`Dev Done`**.
  - **Changes requested** → ticket de vuelta a **`In Progress`** (el dev reworkea en la misma
    branch y vuelve a `/complete-dev`).

```
✓ code-review record posted as a ClickUp comment
✓ Review summary posted on MR/PR !42
✓ Ticket moved to Dev Done

Next: QA can now run /review-outcome to log functional testing findings.
```

---

## Paso 6 — `/review-outcome`: QA

Lo corre una **persona de QA** (ni el autor ni el reviewer), después de probar la feature a mano:

```
/review-outcome TASK-42
```

El skill espera el ticket en `Dev Done` o `QA`. Lo **mueve a `QA`** si hacía falta, te muestra
el contexto del code review previo, y junta los hallazgos de QA: bugs encontrados, cumplimiento
del spec, estabilidad, rondas de revisión y el **veredicto**.

Con eso postea un record `qa-outcome` (JSON) como comment y **ramifica**:

- **Aprobado** → ticket a **`Done`**. 🎉
- **Rejected** → ticket a **`QA Reject`** (el dev revisa los hallazgos y vuelve a arrancar con
  `/start-ticket`).

```
✓ QA outcome record posted to the ClickUp task
✓ Ticket marked Done in ClickUp

Summary:
  Bugs:            none
  Spec compliance: fully_compliant
  Verdict:         approved
```

Con eso, **`TASK-42` quedó en `Done`** y recorrió todo el loop.

---

## Resumen: el ticket por la máquina de estados

| Comando | Estado al terminar | Qué pasó |
| --- | --- | --- |
| `/create-ticket` | `Todo` | Task creada en ClickUp + spec local |
| `/ticket-review` | `Todo` | Gate de readiness (mecánico + semántico + cross-layer) |
| `/start-ticket` | `In Progress` | Gate + branch + `implement` agent |
| `/complete-dev` | `In Review` *(o vuelve a `In Progress`)* | `verify` agent → push + MR |
| *(CI review-agent)* | `In Review` | 3 specialists automáticos en el PR |
| `/pr-review` | `Dev Done` *(o `In Progress`)* | Code review humano |
| `/review-outcome` | `Done` *(o `QA Reject`)* | QA |

---

## Más allá del core loop

El harness trae también skills que no entran en este recorrido lineal:

- **`/create-chunk`** + **`/update-plan`** — para arrancar una feature grande de una: varios
  tickets + specs de chunk + un plan de implementación, todo de un saque.
- **`/feedback`** — registrar una observación suelta sobre el workflow (sin atarla a un ticket).
- **`/ai-insights`** — agregar todos los workflow records (`dev-complete` / `code-review` /
  `qa-outcome`) en un reporte.
- **`/improve-agents`** — agrupa patrones de feedback y propone ediciones de bajo riesgo al
  propio harness (CLAUDE.md, reglas, agentes) vía un PR de GitHub.
- **`/mutation-tests`** — orquestador de mutation testing.

Y lo único que queda por completar por proyecto es la **Capa 3** (las reglas del stack en
`.claude/rules/`, los comandos del gate de verify/implement, y las particularidades del stack
del review-agent). El [`README.md`](README.md) explica cómo.
