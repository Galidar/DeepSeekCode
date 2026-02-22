---
description: Delegate a code task to DeepSeek Code using oneshot mode
argument-hint: <description of the task to delegate>
---

Eres Claude Code y vas a delegar una tarea de generacion de codigo a DeepSeek Code, tu subordinado especialista en codigo.

Carga y sigue todas las guias de la skill `deepseek-code-mastery` de este plugin para entender el sistema completo.

**Tu tarea:** Basandote en la solicitud del usuario "$ARGUMENTS", construye y ejecuta el comando de delegacion correcto.

## REGLA CRITICA: No contaminar mensajes de tarea

**NUNCA agregues frases de acknowledgment a la tarea delegada.** El sistema maneja Phase 1/2 internamente. Si escribes:

```
--delegate "Crea un formulario de login, di solo OK"
```

DeepSeek LITERALMENTE dira "OK" en vez de crear el formulario. El texto que pasas en `--delegate` es el **mensaje de tarea puro** (Phase 3). **PROHIBIDO** agregar:
- "di solo OK", "responde OK", "solo di OK"
- "responde unicamente con codigo"
- "confirma que entendiste"
- Cualquier instruccion de formato de respuesta

El system prompt, skills y acknowledgments son automaticos (Phase 1 y Phase 2). Tu solo envias la tarea limpia.

## Proceso Token-Eficiente

**REGLA CRITICA: Nunca uses Write para guardar el codigo generado por DeepSeek. Siempre usa pipe directo a disco.**

El flujo eficiente tiene 3 fases:

### Fase 1: Analiza y prepara

1. **Analiza la tarea**: Determina que archivos se generaran y donde guardarlos.
2. **Decide los flags**:
   - Template con TODOs -> `--template ruta/archivo`
   - Archivo de referencia de estilo -> `--context ruta/archivo`
   - Correccion de intento anterior -> `--feedback "errores especificos"`
   - Tareas grandes -> `--max-retries 2`
   - `--negotiate-skills`: DeepSeek elige sus skills (~15s extra, pero mas preciso)

### Fase 2: Ejecuta con pipe directo a disco

**Para un solo archivo** (lo mas comun):
```bash
cd DEEPSEEK_DIR && python run.py --delegate "TAREA_PRECISA" --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --output "RUTA/DESTINO/archivo.ext" --preview 5
```

**Para multiples archivos** (DeepSeek genera varios):
```bash
cd DEEPSEEK_DIR && python run.py --delegate "TAREA_PRECISA" --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --split --dir "RUTA/PROYECTO/" --preview 5
```

IMPORTANTE:
- `DEEPSEEK_DIR` es donde esta `run.py`. Detecta con `git rev-parse --show-toplevel` o busca en la ruta de instalacion.
- El pipe `|` envia la respuesta directo al disco. Claude NUNCA ve el codigo completo.
- `--preview 5` incluye las primeras 5 lineas en la metadata para verificacion rapida.
- Claude solo recibe metadata: lineas, chars, exito, duracion, archivos guardados.

### Fase 3: Supervisa y corrige

1. **Lee la metadata** que imprime save_response (success, lines, chars, saved_to).
2. **Verifica rapidamente** el archivo guardado leyendo solo las primeras lineas si es necesario.
3. **Aplica correcciones** con el tool Edit si hay bugs — ediciones quirurgicas, NO reescribir.
4. Si `success: false` o `truncated: true` -> reduce scope o usa `/deepseek-code:quantum`.

## Por que este flujo

| Flujo antiguo | Flujo eficiente |
|:---:|:---:|
| DeepSeek genera ~5000 tokens | DeepSeek genera ~5000 tokens |
| Claude recibe TODO el codigo | Claude recibe ~200 tokens metadata |
| Claude REESCRIBE con Write (~5000 tokens) | Archivo se guarda directo por pipe |
| **Total Claude: ~10000 tokens** | **Total Claude: ~400 tokens** |
| **Ahorro: 0%** | **Ahorro: ~96%** |

## Sesiones Persistentes (v2.5+)

Usa `--session <nombre>` para mantener continuidad entre llamadas.

**Primera llamada** — envia system prompt + tarea (sesion nueva):
```bash
cd DEEPSEEK_DIR && python run.py --delegate "TAREA" --session "auth-module" --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --output "RUTA/archivo.ext" --preview 5
```

**Llamadas posteriores** — DeepSeek ya tiene contexto completo:
```bash
cd DEEPSEEK_DIR && python run.py --delegate "agrega password reset al modulo" --session "auth-module" --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --output "RUTA/archivo.ext" --preview 5
```

**Reportar errores** al mismo chat que genero el codigo:
```bash
cd DEEPSEEK_DIR && python run.py --delegate "error en linea 45: TypeError..." --session "auth-module" --feedback "stack trace..." --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --output "RUTA/archivo.ext" --preview 5
```

## Routing Inteligente de Sesiones (v2.6)

**NUEVO**: Cada sesion DeepSeek es una "esponja" independiente que absorbe conocimiento. Claude decide a cual sesion enviar cada mensaje.

### Consultar el digest de sesiones

Antes de delegar, consulta que sesiones existen y que saben:
```bash
cd DEEPSEEK_DIR && python run.py --session-digest
```

Retorna JSON con:
- `active_sessions`: lista de sesiones con nombre, topic, summary, skills cargadas, tokens invertidos
- `transferable`: sesiones con suficiente contexto para transferir conocimiento

### Transferencia de conocimiento entre chats

Si Chat A diseno el sistema de autenticacion y Chat B necesita crear la API que lo usa:
```bash
cd DEEPSEEK_DIR && python run.py --delegate "crear API endpoints" --session "api-module" \
    --transfer-from "delegate:auth-module" --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --output "RUTA/api.ext" --preview 5
```

`--transfer-from` inyecta un resumen compacto del conocimiento de la sesion origen (topic, summary, skills cargadas) como contexto Phase 2. La sesion destino recibe el conocimiento sin duplicar tokens.

### Inyeccion Phase 2 (como funciona internamente)

El sistema v2.6 separa el contexto en fases:
1. **Phase 1**: System prompt (solo primera vez) -> DeepSeek responde "OK"
2. **Phase 2**: Inyecciones individuales (skills, memoria, knowledge) -> cada una con ack especifico
3. **Phase 3**: Mensaje del usuario (limpio, sin contexto extra)

Cada inyeccion se trackea por sesion. En llamadas posteriores, solo se envian inyecciones NUEVAS. Ahorro: ~99.8% en la 2da llamada al mismo chat.

### Gestion de sesiones

```bash
python run.py --session-list --json        # ver sesiones activas
python run.py --session-digest             # digest completo para routing
python run.py --session-close "nombre"     # cerrar sesion
python run.py --session-close-all          # cerrar todas
```

## Auto-Continuacion

Si DeepSeek trunca su respuesta, el sistema automaticamente detecta el truncamiento y envia "continua" hasta 3 veces. Las partes se concatenan. Es transparente — save_response recibe la respuesta completa.

## Tips

- La tarea debe ser PRECISA y DESCRIPTIVA. "crea un endpoint" es malo. "crea endpoint POST /api/users con validacion Zod de email+name+password, hash bcrypt, y respuesta 201 con user sin password" es bueno.
- DeepSeek responde SOLO codigo, sin markdown ni explicaciones.
- Si el resultado es muy grande para una delegacion, considera `/deepseek-code:multi-step` o `/deepseek-code:quantum`.
- Para refinamiento iterativo, usa `/deepseek-code:converse`.
- Para continuidad entre llamadas, usa `--session "nombre"` — DeepSeek mantiene contexto.
- Usa `--session-digest` para decidir a cual chat enviar cada tarea.
- Usa `--transfer-from` para compartir conocimiento entre chats sin duplicar tokens.
