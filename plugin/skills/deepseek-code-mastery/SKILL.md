---
name: deepseek-code-mastery
description: Referencia completa para operar DeepSeek Code (128K contexto, V3.2) como sistema multi-agente subordinado a Claude Code. v2.1 incluye V3.2 auto-select model (deepseek-reasoner para codigo complejo, 64K output), thinking mode web, smart template chunking, max_tokens adaptivo, dual quantum sessions, multi-step, surgical memory, global memory, y protocolo de colaboracion 3-fases. Usar cuando el usuario pida delegar codigo, generar funciones, crear features, o cualquier tarea de generacion masiva.
---

# DeepSeek Code Mastery — Guia Completa para Claude Code

## 1. Overview

**DeepSeek Code** es un asistente de programacion local basado en DeepSeek V3 (API o sesion web) con herramientas MCP (filesystem, shell, search, memory, Serena). Claude Code actua como **cirujano** (planifica, revisa, orquesta) y delega el **trabajo pesado de generacion de codigo** a DeepSeek Code como subordinado.

**Ubicacion del proyecto:** Directorio donde se clono/instalo DeepSeek Code (contiene `run.py`)
**Entry point:** `python run.py` (o `DeepSeekCode.exe`)
**Lenguaje:** Python 3 (PyQt5 para login web, asyncio para networking)

> **Nota sobre rutas:** En esta documentacion, `<DEEPSEEK_DIR>` se refiere al directorio raiz del proyecto DeepSeek Code (donde esta `run.py`) y `<APPDATA>` se refiere al directorio de datos de la aplicacion (`%APPDATA%\DeepSeek-Code` en Windows, `~/.config/DeepSeek-Code` en Linux/macOS). Detecta estas rutas automaticamente al ejecutar comandos.

### Modos de Operacion

| Modo | Flag CLI | Descripcion |
|------|----------|-------------|
| Interactivo | (ninguno) | Chat con herramientas, modo web o API |
| One-shot | `-q "pregunta"` | Pregunta unica, respuesta y sale |
| Agente | `--agent "meta"` | Autonomo multi-paso con herramientas |
| **Delegacion** | `--delegate "tarea"` | **PRINCIPAL**: Claude Code delega codigo |
| **Quantum** | `--quantum "tarea"` | Delegacion paralela dual + merge |
| **Multi-session** | `--multi "tarea"` | N instancias paralelas con roles |
| **Multi-step** | `--multi-step plan.json` | Plan multi-paso secuencial/paralelo |
| Conversacion | `--converse "msg"` | Dialogo multi-turno iterativo |

### Flags Globales Nuevos (v2.0)

| Flag | Descripcion |
|------|-------------|
| `--negotiate-skills` | DeepSeek elige sus propias skills del catalogo |
| `--multi "tarea"` | Modo multi-sesion (N instancias) |
| `--roles PRESET` | Preset de roles para multi-sesion |
| `--instances N` | Numero de instancias (0=auto) |
| `--pipeline` | Modo pipeline secuencial (gen -> review -> fix) |

### Sistema Adaptivo de Prompts (v2.0)

El sistema clasifica cada tarea en 5 niveles y adapta automaticamente:
- **CHAT (0)**: "Hola" → ~25 tokens de system prompt, 0 skills
- **SIMPLE (1)**: "Que es un closure?" → ~50 tokens, 0 skills
- **CODE_SIMPLE (2)**: "Arregla typo" → ~80 tokens, max 10K skills
- **CODE_COMPLEX (3)**: "Sistema de inventario" → ~600 tokens, max 40K skills
- **DELEGATION (4)**: Via --delegate → prompt completo, max 80K skills

### Negociacion de Skills (v2.0)

Con `--negotiate-skills`, DeepSeek recibe un catalogo compacto (~2K tokens) de las 51 skills disponibles y elige cuales necesita realmente. Esto reemplaza la inyeccion heuristica y reduce tokens desperdiciados.

### Multi-Session (v2.0)

Generaliza quantum (2 instancias) a N instancias con roles:
- **generate-review**: Generador + reviewer (default)
- **full-pipeline**: Generador + reviewer + tester
- **dual-generator**: Dos generadores independientes
- **specialist-pair**: Dos especialistas en dominios diferentes

---

## 2. Rutas y Configuracion

### Paths Criticos

```
Proyecto:    <DEEPSEEK_DIR>/                          (directorio raiz con run.py)
Config:      <APPDATA>/config.json                    (%APPDATA%\DeepSeek-Code en Windows)
WASM:        <APPDATA>/sha3_wasm_bg.wasm              (auto-descargado al primer login)
Skills:      <DEEPSEEK_DIR>/skills/                   (51 archivos .skill)
Memory:      <APPDATA>/memory.md
Surgical:    <APPDATA>/surgical_memory/
Global:      <APPDATA>/global_memory.json
EXE:         <DEEPSEEK_DIR>/dist/DeepSeekCode.exe     (si se compilo con PyInstaller)
```

### config.json (campos importantes)

```json
{
  "bearer_token": "...",       // Token de sesion web (auto via /login)
  "cookies": "...",            // Cookies de sesion web
  "api_key": "...",            // No usado (solo modo web)
  "wasm_path": "...",          // Ruta al WASM para firma de requests web
  "allowed_paths": [],         // Directorios permitidos (vacio = todo)
  "allowed_commands": [],      // Comandos shell permitidos
  "serena_enabled": true,      // Serena code intelligence
  "serena_project": "...",     // Proyecto activo en Serena
  "summary_threshold": 80,     // % de contexto antes de resumir
  "skills_dir": "...",         // Directorio de skills
  "auto_select_model": true,   // Auto deepseek-reasoner para CODE_COMPLEX+DELEGATION
  "thinking_enabled": true,    // Thinking mode en web sessions para codigo
  "pool_size": 5,              // Pool size para futuro multi-session (2-10, quantum actual usa 2)
  "chunk_threshold_tokens": 30000  // Umbral para chunking de templates
}
```

### Autenticacion

DeepSeek Code soporta **dos modos**: web (gratis) y API (pagado). Ambos usan DeepSeek V3.2 con **128K tokens de contexto**.

- **Modo Web**: `bearer_token` + `cookies` + WASM para firmar requests. Login via `/login` (PyQt5 WebEngine). Tokens expiran cada ~24-48h, re-login automatico si falla. **Gratis**.
- **Modo API**: `api_key` de platform.deepseek.com. Pago por tokens.
- **128,000 tokens de contexto** — las skills se inyectan generosamente (hasta 80K) dejando espacio para template + respuesta

---

## 3. Delegacion Oneshot (`--delegate`)

### Sintaxis Completa

```bash
python run.py --delegate "TAREA" [opciones] --json
```

**Opciones:**

| Flag | Descripcion | Ejemplo |
|------|-------------|---------|
| `--delegate "tarea"` | Descripcion de la tarea | `--delegate "crea endpoint REST /api/users"` |
| `--template archivo` | Archivo con esqueleto TODO | `--template game.js` |
| `--context archivo` | Archivo de referencia de estilo | `--context existing-code.js` |
| `--feedback "texto"` | Correccion de intento anterior | `--feedback "falta validacion de input"` |
| `--max-retries N` | Reintentos si validacion falla (default: 1) | `--max-retries 2` |
| `--no-validate` | Desactivar auto-validacion | `--no-validate` |
| `--project-context ruta` | CLAUDE.md del proyecto | `--project-context ./CLAUDE.md` |
| `--json` | Output JSON estructurado | `--json` |
| `--config ruta` | Config alternativa | `--config ./mi-config.json` |

### Flujo Interno de Delegacion

```
1. Carga config.json y crea DeepSeekCodeClient
2. SurgicalMemory.pre_delegation() -> briefing del proyecto (reglas, errores previos)
3. GlobalMemory.pre_delegation() -> briefing personal cross-proyecto (estilo, skills, errores)
4. build_delegate_skills_context():
   a. Carga CORE_SKILLS siempre (programming-foundations, data-structures, common-errors)
   b. Detecta skills Domain relevantes por keywords de la tarea
   c. Llena hasta el budget de tokens (core:15K + domain:45K + specialist:20K = 80K)
5. enriched_system = DELEGATE_SYSTEM_PROMPT + skills_context + surgical_briefing + global_briefing
6. build_delegate_prompt(task, template, context, feedback) -> user_message
7. DeepSeek genera la respuesta (codigo puro, sin markdown)
8. delegate_validator valida: no truncamiento, TODOs completos, sin errores canvas
9. Si falla validacion y quedan retries: re-intenta con feedback de errores
10. SurgicalMemory.post_delegation() -> aprende de resultado del proyecto
11. GlobalMemory.post_delegation() -> aprende patrones personales cross-proyecto
12. Retorna JSON: { success, response, validation, retries_used, duration_s }
```

### Interpretacion del JSON de Respuesta

```json
{
  "success": true,
  "response": "// === TODO 1: ENEMY_TYPES ===\nlet ENEMY_TYPES = {...}\n...",
  "mode": "delegate",
  "had_template": true,
  "had_context": false,
  "duration_s": 12.5,
  "validation": {
    "valid": true,
    "truncated": false,
    "issues": [],
    "todos_found": ["ENEMY_TYPES", "renderMap"],
    "todos_missing": [],
    "stats": {"lines": 150, "functions": 8}
  },
  "token_usage": {
    "system_prompt": 7000,
    "skills_injected": 35000,
    "surgical_briefing": 1200,
    "global_briefing": 500,
    "template": 3000,
    "context_file": 0,
    "user_prompt": 250,
    "total_input": 46950,
    "response_estimated": 8500,
    "total_estimated": 55450,
    "context_remaining": 81050,
    "context_used_percent": "36.7%"
  }
}
```

**Campos clave:**
- `success: false` + `validation.truncated: true` = respuesta cortada, reducir scope
- `success: false` + `validation.todos_missing: ["renderMap"]` = TODOs no completados
- `success: true` + `response` = codigo listo para usar
- `token_usage.context_used_percent` = cuanto del 128K se consumio
- `token_usage.skills_injected` = tokens de conocimiento inyectado

### Cuando Usar --template vs Tarea Libre

**Usar --template cuando:**
- Tienes un archivo esqueleto con marcadores `// TODO: nombre` que DeepSeek debe rellenar
- Quieres controlar la estructura exacta del codigo
- El resultado debe integrarse en un archivo existente

**Usar tarea libre (sin --template) cuando:**
- Pides generar codigo desde cero
- La tarea es autocontenida (un endpoint, una funcion, un componente)
- No hay estructura preexistente que seguir

### Cuando Usar --context

Pasa `--context archivo.js` cuando quieres que DeepSeek **imite el estilo** de codigo existente: nombres de variables, patrones, estructura, convenciones del proyecto. DeepSeek lo lee y adapta su output para ser consistente.

### Cuando Usar --feedback

Pasa `--feedback "descripcion de errores"` cuando un intento anterior fallo y quieres que DeepSeek corrija errores especificos. El feedback se inyecta como "CORRECCION IMPORTANTE" en el prompt.

### Ejemplo Completo de Delegacion

```bash
# Tarea libre - generar desde cero
python run.py --delegate "crea un servidor Express con endpoints CRUD para usuarios, validacion Zod, y middleware de auth JWT" --json

# Con template - rellenar TODOs
python run.py --delegate "implementa las funciones de combate" --template game-combat.js --context game-player.js --json

# Con feedback - corregir intento anterior
python run.py --delegate "implementa sistema de inventario" --template inventory.js --feedback "falta drag-and-drop entre slots, el grid debe ser 6x4" --json
```

---

## 4. Quantum Bridge (`--quantum`)

### Que Es

Delegacion **paralela dual**: lanza 2 sesiones de DeepSeek simultaneamente, cada una con un "angulo" diferente (perspectiva/enfoque), y luego **mergea** las respuestas en una sola. Ideal para tareas complejas donde dos perspectivas producen mejor resultado.

### Sintaxis

```bash
python run.py --quantum "TAREA" [--template archivo] [--quantum-angles "angulo1,angulo2"] --json
```

### Angulos

**Automaticos** (sin `--quantum-angles`): el sistema detecta el tipo de tarea y asigna angulos:
- `game_full` -> "gameplay,visual"
- `fullstack` -> "frontend,backend"
- `refactor` -> "architecture,implementation"
- `template_split` -> "core_logic,visual_audio"

**Manuales** (con `--quantum-angles`):
```bash
--quantum-angles "logica,render"
--quantum-angles "api,database"
--quantum-angles "core,ui"
```

### Estrategias de Merge (en cascada)

1. **Template-guided**: Si hay template con TODOs, asigna cada TODO al angulo que mejor lo resolvio
2. **Function-based**: Extrae funciones de ambas respuestas, elige la mejor version de cada una
3. **Raw**: Concatena ambas respuestas eliminando duplicados

### Cuando Usar Quantum vs Delegate Simple

| Escenario | Recomendacion |
|-----------|---------------|
| Tarea simple (<200 lineas resultado) | `--delegate` |
| Feature compleja multi-aspecto | `--quantum` |
| Template con >8 TODOs | `--quantum` (menos truncamiento) |
| Tarea fullstack (frontend+backend) | `--quantum --quantum-angles "frontend,backend"` |
| Correccion de errores | `--delegate --feedback` (no quantum) |

### Ejemplo

```bash
# Juego completo con gameplay + visual
python run.py --quantum "crea un juego de tower defense con oleadas, upgrades y particulas" --template tower-defense.js --json

# Fullstack
python run.py --quantum "crea API REST + frontend React para gestionar tareas" --quantum-angles "api,frontend" --json
```

---

## 5. Multi-Step (`--multi-step`)

### Que Es

Ejecuta un plan de multiples pasos secuenciales y/o paralelos. Cada paso es una delegacion independiente que puede depender de resultados anteriores.

### Sintaxis

```bash
python run.py --multi-step plan.json --json
# O inline:
python run.py --multi-step-inline '{"steps":[...]}' --json
```

### Formato del Plan JSON

```json
{
  "steps": [
    {
      "id": "step1",
      "task": "crea el modelo de datos de Usuario",
      "template": "models/user.ts",
      "validate": true,
      "max_retries": 2
    },
    {
      "id": "step2",
      "task": "crea los endpoints CRUD usando el modelo",
      "template": "routes/users.ts",
      "context_from": ["step1"],
      "validate": true
    },
    {
      "id": "step3a",
      "task": "crea tests unitarios para el modelo",
      "parallel_group": "tests"
    },
    {
      "id": "step3b",
      "task": "crea tests de integracion para los endpoints",
      "context_from": ["step2"],
      "parallel_group": "tests"
    },
    {
      "id": "step4",
      "task": "crea componente React complejo con formulario",
      "dual_mode": true
    }
  ]
}
```

### Campos de StepSpec

| Campo | Tipo | Descripcion |
|-------|------|-------------|
| `id` | string | Identificador unico del paso |
| `task` | string | Descripcion de la tarea |
| `template` | string? | Ruta a template con TODOs |
| `context_from` | string[]? | IDs de pasos cuyo resultado se inyecta como contexto |
| `validate` | bool? | Activar validacion (default: true) |
| `max_retries` | int? | Reintentos (default: 1) |
| `parallel_group` | string? | Pasos con mismo grupo se ejecutan en paralelo |
| `dual_mode` | bool? | Usar Quantum Bridge para este paso |

### Flujo de Ejecucion

1. Agrupa pasos por `parallel_group`
2. Ejecuta grupos secuencialmente, pero pasos dentro del grupo en paralelo
3. `context_from` inyecta el `response` de pasos anteriores como `--context`
4. `dual_mode: true` ejecuta el paso via Quantum Bridge en vez de delegate simple
5. Resultado: JSON con array de resultados por paso

---

## 6. Sistema de Skills 3-Tier

### Arquitectura

DeepSeek Code tiene un sistema de inyeccion automatica de conocimiento en 3 niveles:

**Tier 1 - Core Knowledge** (SIEMPRE inyectado en delegacion, ~15K tokens):
- `programming-foundations` — SOLID, GoF patterns, Clean Code, Error Handling, Async, Testing
- `data-structures-algorithms` — O(), estructuras, algoritmos, spatial
- `common-errors-reference` — 27+ errores comunes con soluciones

**Tier 2 - Domain Skills** (por relevancia de keywords, hasta ~45K tokens):
- Se activan segun las palabras clave de la tarea
- Con 45K tokens de budget, pueden entrar 5-8 skills completas
- Ejemplos: `canvas-2d-reference`, `math-foundations`, `physics-simulation`, `typescript-advanced`, `database-patterns`, `security-auth-patterns`, `backend-node-patterns`, `css-modern-patterns`
- 46 skills mapeadas en SKILL_KEYWORD_MAP

**Tier 3 - Specialist** (si hay espacio, ~20K tokens):
- Skills de nicho que puntuaron pero no entraron en Tier 2
- Con 20K tokens, pueden entrar 2-3 skills adicionales

### Budget de Tokens (128K Contexto)

DeepSeek V3.2 tiene **128,000 tokens de contexto**. El budget de skills esta
diseñado para maximizar conocimiento inyectado dejando espacio para template y respuesta.

```
Modo Delegacion (128K contexto):
  Core:       15,000 tokens (siempre presente, ~60K chars)
  Domain:     45,000 tokens (por relevancia, ~180K chars)
  Specialist: 20,000 tokens (si hay espacio, ~80K chars)
  TOTAL:      80,000 tokens para skills (~320K chars, 62.5% del contexto)

  + DELEGATE_SYSTEM_PROMPT:  ~7,000 tokens
  + SurgicalMemory briefing: ~3,000 tokens
  + GlobalMemory briefing:   ~2,000 tokens
  + Template + context:      variable
  = ~92,000 tokens de sistema (~72% del contexto de 128K)
  = ~36,000 tokens disponibles para la respuesta de DeepSeek

Modo Interactivo (128K contexto): 80,000 tokens para skills
```

**Nota**: Con 128K de contexto, el budget de 80K para skills es agresivo.
En tareas con templates grandes, el sistema auto-reduce skills inyectadas
para dejar espacio. Para delegaciones simples sin template, el budget completo
funciona bien. `deepseek-reasoner` da hasta 64K output (incluyendo chain-of-thought).

### Skills Disponibles (51 total)

**Fundamentales (Core):** programming-foundations, data-structures-algorithms, common-errors-reference

**Juegos:** canvas-2d-reference, physics-simulation, game-genre-patterns, web-audio-api, sounds-on-the-web, procedural-generation, character-sprite, custom-algorithmic-art

**Web/Frontend:** modern-javascript-patterns, vercel-react-best-practices, server-side-rendering, css-modern-patterns, interface-design, ui-ux-pro-max, web-design-guidelines, building-native-ui, chat-ui

**Backend:** backend-node-patterns, security-auth-patterns, database-patterns, server-management, java-spring-boot

**TypeScript:** typescript-advanced

**3D/GPU:** webgpu, threejs-shaders, webgpu-threejs-tsl

**Otros:** claude-delegate, project-architecture, code-review-excellence, audit-website, launch-strategy, remotion-best-practices, json-canvas, document-chat-interface, official-skill-creator, skill-judge, apollo-mcp-server, cloudflare-mcp-server, audiocraft-audio-generation, manaseed-integration, rivetkit-client-javascript, ue57-rhi-api-migration, create-design-system-rules, custom-web-artifacts-builder, advanced-coding

### Crear Skills Nuevas

Las skills son archivos `.skill` (ZIP conteniendo `SKILL.md` con frontmatter YAML).

Para crear una nueva:
1. Crear archivo `.md` con frontmatter `---\nname: mi-skill\ndescription: ...\n---`
2. Empaquetar como ZIP renombrando a `.skill`
3. Colocar en `<DEEPSEEK_DIR>/skills/`
4. Agregar keywords en `src/deepseek_code/skills/skill_constants.py` -> `SKILL_KEYWORD_MAP`

---

## 7. Sistema de Memoria Dual

### 7a. SurgicalMemory (Nivel 1 — Por Proyecto)

Sistema de memoria persistente que conecta Claude Code (cirujano/planificador) con DeepSeek Code (asistente/ejecutor). Aprende de cada delegacion para mejorar las siguientes.

**Flujo:**
```
ANTES de delegar:
  pre_delegation() ->
    1. Detecta proyecto (sube directorios buscando CLAUDE.md, .git, package.json)
    2. Carga store JSON del proyecto (%APPDATA%/surgical_memory/{name}_{hash}.json)
    3. Lee CLAUDE.md si existe
    4. Construye briefing con budget de 3000 tokens:
       Prioridad: rules > errors > conventions > architecture > patterns > claude_md

DESPUES de delegar:
  post_delegation() ->
    1. Aprende reglas de errores detectados
    2. Registra en historial: tarea, modo, exito, duracion
    3. Guarda store actualizado a disco
```

**Almacenamiento:**
```
%APPDATA%\DeepSeek-Code\surgical_memory\
  LiminalCrown_a1b2c3d4.json   # Store del proyecto LiminalCrown
  MyWebApp_e5f6g7h8.json       # Store de otro proyecto
```

### 7b. GlobalMemory (Nivel 2 — Personal Cross-Proyecto)

Sistema de aprendizaje personal que acumula patrones del desarrollador a traves de TODOS los proyectos. Se vuelve mas inteligente con cada delegacion.

**Lo que aprende (7 dimensiones):**
1. Estilo de codigo: let vs const, camelCase vs snake_case, idioma de comentarios
2. Skills por exito real: rankea las 51 skills por tasa de exito (no solo keywords)
3. Complejidad optima: sweet spot de TODOs por template y tokens input (EMA)
4. Rendimiento por modo: delegate vs quantum vs multi-step (exito y duracion)
5. Errores cross-proyecto: patrones que se repiten en multiples proyectos
6. Keywords de tarea: que temas tienen mejor tasa de exito
7. Recomendaciones automaticas: briefing con skills a usar/evitar

**Briefing inyectado (~2000 tokens max):**
```
== PERFIL PERSONAL DEL DESARROLLADOR (GlobalMemory) ==
ESTILO DE CODIGO:
- Usar let (no const) — 100% preferencia historica
- Naming: camelCase
- Comentarios en espanol

SKILLS RECOMENDADAS (por tasa de exito real):
- canvas-2d-reference: 92% exito (12 usos)
- physics-simulation: 88% exito (8 usos)
EVITAR:
- threejs-shaders (30% exito, trunca 60%)

COMPLEJIDAD OPTIMA:
- TODOs por template: 5 (sweet spot historico)
- Input tokens optimo: ~40,000

RENDIMIENTO POR MODO:
- delegate: 85% exito (50 usos, ~45s promedio)
- quantum: 78% exito (12 usos, ~90s promedio)
== FIN PERFIL PERSONAL ==
```

**Almacenamiento:** `%APPDATA%\DeepSeek-Code\global_memory.json` (unico archivo)

**Compactacion automatica:**
- Max 30 skill combos, max 20 cross-project errors, max 50 task keywords
- Purga skills con <2 inyecciones y >90 dias sin uso

### Orden de inyeccion en system prompt

```
DELEGATE_SYSTEM_PROMPT       (~7K tokens, base)
+ skills_extra               (~80K tokens, skills 3-tier)
+ surgical_briefing          (~3K tokens, contexto del proyecto)
+ global_briefing            (~2K tokens, perfil personal)
= enriched_system            (~92K tokens, ~72% del contexto 128K)
```

---

## 8. Modo Interactivo y Agente

### Interactivo (default)

```bash
python run.py
# o
DeepSeekCode.exe
```

Chat con herramientas MCP: filesystem (read/write/edit/list/delete/move/copy), shell, web search, memory, Serena.

**Comandos internos:**
- `/exit` — Exit
- `/skills` — List available skills
- `/agent <goal>` — Run autonomous agent
- `/skill <name> [args]` — Run skill workflow
- `/serena [start|stop|status]` — Control Serena
- `/login` — Web login (PyQt5 WebEngine)
- `/test` — Verify connection
- `/health` — Session health check
- `/account` — Multi-account management
- `/lang` — Change language (English/Spanish/Japanese)
- `/keys` — API key help

### Agente Autonomo (`--agent`)

```bash
python run.py --agent "crea un proyecto React con auth, dashboard y API backend" --json
```

El agente planifica, ejecuta acciones con herramientas, evalua resultados, y adapta su plan. Incluye la palabra `COMPLETADO` cuando termina.

---

## 8.5. DeepSeek V3.2 — Auto-Select, Thinking, Chunking

### Auto-Select de Modelo

El sistema selecciona automaticamente el modelo optimo segun la complejidad:

| Nivel de Tarea | Modelo | max_tokens | Cuando |
|---------------|--------|-----------|--------|
| CHAT / SIMPLE | `deepseek-chat` | 1K-2K | Preguntas, conversacion |
| CODE_SIMPLE | `deepseek-chat` | 4K | Fixes simples, typos |
| CODE_COMPLEX | `deepseek-reasoner` | 8K | Sistemas, features grandes |
| DELEGATION | `deepseek-reasoner` | 16K | Via --delegate, templates |

`deepseek-reasoner` da 64K output max con chain-of-thought (vs 8K de deepseek-chat).
Se activa automaticamente — no necesita flags especiales.
Desactivar con `"auto_select_model": false` en config.json.

### Thinking Mode (Web Sessions)

Cuando `"thinking_enabled": true` en config, las sesiones web envian `thinking_enabled: true`
en el payload SSE, activando el razonamiento profundo de DeepSeek para codigo.

### Template Chunking

Templates >30K tokens se dividen automaticamente en chunks por bloques TODO:
1. Detecta `// === TODO 1A: nombre ===` markers
2. Divide en chunks de ~5K tokens cada uno
3. Cada chunk recibe contexto del output anterior
4. Si no hay TODOs, divide por lineas (fallback)

Umbral configurable: `"chunk_threshold_tokens": 30000` en config.json.

### Sesiones Paralelas (Quantum)

Quantum Bridge usa `DualSession` con 2 clientes en paralelo.
La funcion `create_pool_clients(N)` esta disponible en quantum_helpers.py
para futuras implementaciones multi-session, pero actualmente el runner
quantum solo usa 2 sesiones.

```python
# quantum_helpers.py - disponible para uso futuro
from cli.quantum_helpers import create_pool_clients
clients = create_pool_clients(config, mcp_server)  # Default: 5
```

Config `"pool_size": N` (clamp: 2-10) para cuando se integre multi-session.

---

## 9. Patrones de Uso Optimos

### Receta: Generar Codigo de Juego

```bash
# 1. Crear template con TODOs
# 2. Pasar un juego existente similar como contexto
python run.py --delegate "implementa juego SHMUP con oleadas, power-ups y boss" \
  --template shmup-template.js \
  --context existing-game.js \
  --json
```

**Tip:** DeepSeek inyecta automaticamente: canvas-2d-reference, physics-simulation, game-genre-patterns, web-audio-api, math-foundations.

### Receta: Backend Completo

```bash
# Quantum con angulos api + database
python run.py --quantum "crea API REST completa para e-commerce: productos, carrito, ordenes, auth JWT" \
  --quantum-angles "api,database" \
  --json
```

**Tip:** DeepSeek inyecta: backend-node-patterns, security-auth-patterns, database-patterns, typescript-advanced.

### Receta: Feature Multi-Archivo

```bash
# Crear plan JSON
echo '{
  "steps": [
    {"id": "model", "task": "modelo TypeScript de Usuario con Zod schema"},
    {"id": "api", "task": "endpoints Express CRUD", "context_from": ["model"]},
    {"id": "tests", "task": "tests con vitest", "context_from": ["model", "api"]}
  ]
}' > plan.json

python run.py --multi-step plan.json --json
```

### Receta: Debugging/Correccion

```bash
# Primer intento
python run.py --delegate "crea sistema de inventario drag-and-drop" --template inventory.js --json

# Si falla, corregir con feedback
python run.py --delegate "crea sistema de inventario drag-and-drop" \
  --template inventory.js \
  --feedback "el drag no funciona: falta preventDefault en dragover, los items no se renderizan en el slot destino" \
  --json
```

### Receta: Generacion Rapida sin Template

```bash
# Solo una funcion/componente
python run.py --delegate "funcion JavaScript que implementa A* pathfinding en una grid 2D con obstaculos" --json

# Un componente React completo
python run.py --delegate "componente React TypeScript de tabla paginada con sorting, filtering y seleccion multiple" --json
```

---

## 10. Errores Comunes y Soluciones

### Truncamiento (respuesta cortada)

**Sintoma:** `validation.truncated: true`, respuesta incompleta
**Causa:** deepseek-chat tiene limite de 8K output (4K default). deepseek-reasoner soporta hasta 64K output (incluye CoT).
**Soluciones:**
1. Usar `--template` para que solo responda los TODOs (no repita codigo)
2. Reducir numero de TODOs en el template
3. Usar `--quantum` (split en 2 sesiones = doble capacidad)
4. Agregar en la tarea: "funciones de maximo 20 lineas, sin comentarios"

### Validacion Fallida

**Sintoma:** `success: false`, `validation.errors` tiene mensajes
**Causa:** Auto-validador detecto problemas
**Soluciones:**
1. `--max-retries 2` para auto-reintentar con feedback
2. Re-ejecutar con `--feedback "errores especificos"`
3. `--no-validate` si la validacion es falso positivo

### WASM No Encontrado (modo web)

**Sintoma:** Error "WASM not found" o "FileNotFoundError"
**Causa:** `sha3_wasm_bg.wasm` no esta en APPDATA
**Soluciones:**
1. DeepSeek Code lo auto-descarga al conectarse
2. Verificar ruta en config.json `wasm_path`
3. Re-login: `python run.py` -> `/login`

### Credenciales Expiradas

**Sintoma:** Error 401, "Invalid token"
**Causa:** Bearer token o cookies expiraron (tipicamente cada 24-48h)
**Solucion:** Re-login web: `python run.py` -> `/login` -> inicia sesion en DeepSeek

### Security Hook (desarrollo)

**Sintoma:** Write tool rechazado con "Setting innerHTML..."
**Causa:** Hook de seguridad en el proyecto detecta patrones peligrosos en archivos
**Solucion:** No escribir la cadena literal "innerHTML" concatenada en archivos. Usar `textContent`, `DOMParser`, o `document.createElement()`.

---

## 10b. Internationalization (i18n)

DeepSeek Code supports 3 languages: **English** (default), **Spanish**, and **Japanese**.

### Language Selection Flow

1. **First run**: After the ASCII art banner, a language selector appears before login
2. **Subsequent runs**: Language is loaded from `config.json` (`"lang": "en"`)
3. **Runtime change**: Use `/lang` command in interactive mode to switch

### Architecture

- **`cli/i18n.py`**: Central module with `t(key, **kwargs)` function
- **155 translated keys** across EN and ES, 36 for JA
- **Fallback chain**: current_lang → English → raw key
- **Japanese**: 36 most visible keys translated, rest falls back to English
- **Persistence**: `"lang"` field in `config.json`

### Adding Translations

1. Add key-value pairs to `_STRINGS["en"]` and `_STRINGS["es"]` in `cli/i18n.py`
2. Optionally add to `_STRINGS["ja"]` (fallback to English if missing)
3. Use `t("key_name")` in CLI code instead of hardcoded strings
4. For formatted strings: `t("greeting", name="Alice")` with `"greeting": "Hello {name}"`

---

## 11. Estructura del Proyecto DeepSeek Code

```
<DEEPSEEK_DIR>/
├── run.py                           # Entry point -> cli.main
├── src\
│   ├── cli\
│   │   ├── main.py                  # DeepSeekCodeApp, argparse, modes
│   │   ├── i18n.py                  # Internationalization (en/es/ja), t() function
│   │   ├── oneshot.py               # run_delegate_oneshot(), run_agent_oneshot()
│   │   ├── multi_step.py            # run_multi_step() + multi_step_helpers.py
│   │   ├── quantum_runner.py        # run_quantum() -> DualSession
│   │   ├── collaboration.py        # 3-phase protocol: briefing/execution/review + chunking
│   │   ├── commands.py              # Router for /skills, /agent, /serena
│   │   ├── commands_helpers.py      # Helpers: /login, /health, /account, knowledge_skill
│   │   ├── config_loader.py         # load_config(), APPDATA_DIR, SKILLS_DIR
│   │   ├── onboarding.py            # First-time wizard with language selector
│   │   └── ui_theme.py              # Terminal UI rendering
│   └── deepseek_code\
│       ├── client\
│       │   ├── deepseek_client.py   # DeepSeekCodeClient (web + API)
│       │   ├── api_caller.py        # Auto-select model, max_tokens, build_api_params
│       │   ├── task_classifier.py   # TaskLevel enum, classify_task()
│       │   ├── prompt_builder.py    # Build adaptive system prompts
│       │   └── template_chunker.py  # Smart chunking por TODOs/lineas
│       ├── agent\
│       │   ├── engine.py            # AgentEngine (loop autonomo)
│       │   └── prompts.py           # DELEGATE_SYSTEM_PROMPT, build_delegate_prompt()
│       ├── skills\
│       │   ├── loader.py            # SkillLoader (cache + load_multiple)
│       │   ├── skill_injector.py    # build_delegate_skills_context() 3-tier
│       │   └── skill_constants.py   # CORE_SKILLS, SKILL_KEYWORD_MAP, budgets
│       ├── quantum\
│       │   ├── dual_session.py      # DualSession.parallel_chat()
│       │   ├── angle_detector.py    # Auto-deteccion de angulos
│       │   ├── merge_engine.py      # 3 estrategias de merge
│       │   ├── merge_helpers.py     # Funciones auxiliares de merge
│       │   ├── quantum_runner.py    # Orquestador quantum
│       │   └── quantum_helpers.py   # create_shared_mcp_server, create_client, create_pool_clients
│       ├── surgical\
│       │   ├── integration.py       # pre_delegation(), post_delegation()
│       │   ├── store.py             # SurgicalStore (JSON persistente)
│       │   ├── collector.py         # detect_project_root(), extract_claude_md()
│       │   ├── injector.py          # build_briefing() con budget tokens
│       │   └── learner.py           # learn_from_delegation()
│       ├── global_memory\
│       │   ├── global_store.py      # GlobalStore (JSON cross-proyecto)
│       │   ├── global_learner.py    # Extraccion de patrones personales
│       │   ├── global_injector.py   # Briefing perfil personal (2K tokens)
│       │   └── global_integration.py # Fachada fail-safe pre/post
│       ├── delegate\
│       │   ├── bridge_utils.py      # Utilidades compartidas
│       │   └── delegate_validator.py # Validacion de respuestas
│       ├── tools\                   # 12 herramientas MCP
│       ├── server\                  # MCPServer protocol
│       ├── security\                # RateLimiter, sandbox
│       ├── serena\                  # SerenaManager + native tools
│       └── auth\                    # web_login.py (PyQt5)
├── skills\                          # 51 archivos .skill (ZIP con SKILL.md)
└── dist\                            # DeepSeekCode.exe (PyInstaller)
```

---

## 12. Gestion Estrategica de Tokens (128K Budget)

### Contexto: 128K Tokens Disponibles

DeepSeek V3.2 ofrece **128,000 tokens de contexto** (tanto API como web). La clave
es inyectar el conocimiento justo para la tarea, equilibrando skills con espacio
para template y respuesta.

### Desglose del Consumo por Delegacion

Cada delegacion consume tokens en estas categorias:

```
COMPONENTE                   TOKENS ESTIMADOS    FORMULA
─────────────────────────────────────────────────────────
DELEGATE_SYSTEM_PROMPT       ~7,000              len(texto) / 3.5
Skills Tier 1 (Core)        ~5,000-15,000       depende de 3 skills
Skills Tier 2 (Domain)      ~5,000-45,000       depende de relevancia
Skills Tier 3 (Specialist)  ~0-20,000           si hay espacio
SurgicalMemory briefing     ~500-3,000          budget max 3000
GlobalMemory briefing       ~0-2,000            budget max 2000
Template (si existe)         variable            len(template) / 3.5
Context file (si existe)     variable            len(context) / 3.5
User prompt                  ~100-500            len(task) / 3.5
─────────────────────────────────────────────────────────
TOTAL SISTEMA:              ~20,000-92,000       (16-72% del contexto)
DISPONIBLE RESPUESTA:       ~36,000-108,000      (28-84% del contexto)
```

### JSON de Respuesta con token_usage

El JSON de delegacion incluye un campo `token_usage` con el desglose:

```json
{
  "success": true,
  "response": "...",
  "token_usage": {
    "system_prompt": 7000,
    "skills_injected": 35000,
    "surgical_briefing": 1200,
    "global_briefing": 500,
    "template": 3000,
    "context_file": 0,
    "user_prompt": 250,
    "total_input": 46950,
    "response_estimated": 8500,
    "total_estimated": 55450,
    "context_remaining": 81050,
    "context_used_percent": "36.7%"
  }
}
```

### Formulas de Estimacion

DeepSeek Code usa dos formulas segun el componente:
- **skill_injector**: `len(text) // 4` (conservador, ~4 chars/token)
- **context_manager**: `math.ceil(len(text) / 3.5)` (mas preciso)

Para calcular manualmente: `tokens ≈ caracteres / 3.5`

### Optimizacion del Budget

**Regla general**: Equilibrar skills inyectadas con espacio para respuesta.
Con 128K de contexto, ser selectivo con skills para tareas con templates grandes.

- **Tarea simple** (1 funcion): Core + 1-2 Domain = ~25K input, ~103K para respuesta
- **Tarea media** (1 archivo): Core + 3-4 Domain = ~40K input, ~88K para respuesta
- **Tarea compleja** (multi-aspecto): Core + 5-8 Domain = ~60K input, ~68K para respuesta
- **Quantum** (2 sesiones): Cada sesion tiene su propio contexto de 128K

---

## 13. Referencia Rapida de Comandos

```bash
# Delegacion simple
python run.py --delegate "TAREA" --json
python run.py --delegate "TAREA" --template FILE --json
python run.py --delegate "TAREA" --template FILE --context REF --json
python run.py --delegate "TAREA" --feedback "ERRORES" --json

# Quantum dual
python run.py --quantum "TAREA" --json
python run.py --quantum "TAREA" --template FILE --json
python run.py --quantum "TAREA" --quantum-angles "a,b" --json

# Multi-step
python run.py --multi-step plan.json --json
python run.py --multi-step-inline '{"steps":[...]}' --json

# Otros
python run.py -q "pregunta rapida" --json
python run.py --agent "meta autonoma" --json
python run.py                            # Interactivo

# Flags globales
--max-retries N       # Reintentos (default: 1)
--no-validate         # Sin validacion
--project-context X   # CLAUDE.md del proyecto
--config X            # Config alternativa
--json                # Output JSON
```

---

## 14. Decision Tree: Que Modo Usar

```
Tarea de codigo para DeepSeek?
├── Una sola funcion/componente/archivo?
│   ├── Simple (<100 lineas esperadas) -> --delegate "tarea" --json
│   ├── Con estructura predefinida     -> --delegate "tarea" --template X --json
│   └── Corregir intento anterior      -> --delegate "tarea" --feedback "..." --json
│
├── Tarea compleja multi-aspecto?
│   ├── Frontend + Backend             -> --quantum --quantum-angles "frontend,backend"
│   ├── Logica + Visual                -> --quantum --quantum-angles "logica,visual"
│   └── Template con >8 TODOs         -> --quantum --template X
│
├── Multiples archivos independientes?
│   └── Crear plan.json con steps      -> --multi-step plan.json --json
│
└── Tarea autonoma con herramientas?
    └── Necesita leer/escribir archivos -> --agent "meta" --json
```
