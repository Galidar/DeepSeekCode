---
description: Iterative multi-turn dialogue with DeepSeek Code (shared quantum thinking)
argument-hint: <messages separated by | or conversation description>
---

Eres Claude Code y vas a mantener un dialogo iterativo multi-turno con DeepSeek Code, tu subordinado.

Carga y sigue todas las guias de la skill `deepseek-code-mastery` de este plugin.

**Tu tarea:** Basandote en "$ARGUMENTS", construye y ejecuta una conversacion multi-turno con DeepSeek.

## REGLA CRITICA: No contaminar mensajes

**NUNCA agregues frases de acknowledgment a los mensajes de conversacion.** El sistema maneja Phase 1/2 internamente. Si escribes:

```
--converse "Crea la base del sistema, di solo OK"
```

DeepSeek LITERALMENTE dira "OK" en vez de crear el sistema. Cada mensaje que envias es el **contenido puro** (Phase 3). **PROHIBIDO** agregar:
- "di solo OK", "responde OK", "solo di OK"
- "responde unicamente con codigo"
- "confirma que entendiste"
- Cualquier instruccion de formato de respuesta

El system prompt, skills y acknowledgments son automaticos. Tu solo envias los mensajes limpios.

## Proceso Token-Eficiente

**REGLA CRITICA: Nunca uses Write para guardar codigo generado. Siempre usa pipe directo a disco.**

### Fase 1: Prepara los mensajes

1. **Divide la tarea** en turnos logicos de conversacion.
2. **Crea el JSON de entrada**:
   ```json
   {
     "system": "system prompt opcional",
     "messages": ["primer mensaje", "segundo mensaje", "tercer mensaje"]
   }
   ```

### Fase 2: Ejecuta con pipe directo

**Mensaje unico con salida a archivo:**
```bash
cd DEEPSEEK_DIR && python run.py --converse "MENSAJE" --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --output "RUTA/archivo.ext" --preview 5
```

**Multiples turnos con salida multi-archivo:**
```bash
echo '{"messages":["msg1","msg2"]}' > /tmp/converse.json
cd DEEPSEEK_DIR && python run.py --converse-file /tmp/converse.json --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --split --dir "RUTA/PROYECTO/" --preview 3
```

IMPORTANTE: Ejecuta desde el directorio raiz del proyecto DeepSeek Code (donde esta `run.py`).

### Fase 3: Supervisa y corrige

1. **Lee la metadata** — turnos completados, tokens por turno, archivos guardados.
2. **Verifica** resultado leyendo solo las primeras lineas.
3. **Corrige** bugs puntuales con Edit.

## Sesiones Persistentes (v2.5+)

Usa `--session <nombre>` para continuidad entre invocaciones CLI separadas.

```bash
# Invocacion 1: crea sesion
cd DEEPSEEK_DIR && python run.py --converse "crea la base" --session "feature-X" --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --output "RUTA/archivo.ext" --preview 5

# Invocacion 2 (despues): reanuda la misma conversacion
cd DEEPSEEK_DIR && python run.py --converse "agrega validacion" --session "feature-X" --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --output "RUTA/archivo.ext" --preview 5
```

## Routing Inteligente y Knowledge Transfer (v2.6)

**NUEVO**: Cada sesion es una "esponja" independiente. Claude decide a cual enviar cada mensaje.

### Consultar sesiones disponibles

```bash
cd DEEPSEEK_DIR && python run.py --session-digest
```

Retorna JSON con todas las sesiones activas: nombre, topic, summary, skills cargadas, tokens invertidos, y cuales son transferibles.

### Transferir conocimiento entre chats

Si la sesion "delegate:auth-module" diseno la autenticacion y ahora necesitas crear tests iterativos:
```bash
cd DEEPSEEK_DIR && python run.py --converse "crea tests unitarios" --session "test-auth" \
    --transfer-from "delegate:auth-module" --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --output "RUTA/tests.ext" --preview 5
```

La sesion destino recibe un resumen compacto del conocimiento de la sesion origen sin duplicar tokens. El transfer se registra bidireccionalmente: la sesion origen sabe a quien envio, la destino sabe de quien recibio.

### Inyeccion Phase 2 inteligente

El sistema v2.6 inyecta contexto de forma granular:
1. **Phase 1**: System prompt (solo primera vez)
2. **Phase 2**: Skills, memoria quirurgica, memoria global, knowledge transfers — cada uno como mensaje independiente, trackeado per-sesion
3. **Phase 3**: Mensaje del usuario (limpio)

En turnos posteriores, solo se envian inyecciones NUEVAS. Ahorro: ~99.5% en turno 2+.

### Summaries automaticos

Despues de cada intercambio, el sistema genera un summary local (0 tokens extra) que clasifica el tipo de actividad (codigo, diseno, correccion, consulta) y trackea el topic de la sesion. Esto alimenta el `--session-digest` para routing inteligente.

## Cuando Usar Converse

- Refinamiento iterativo: "crea la base" -> "ahora agrega validacion" -> "optimiza"
- Debugging colaborativo: enviar error -> diagnostico -> fix -> verificar
- Diseno progresivo: construir feature paso a paso con feedback entre turnos
- Cualquier tarea donde DeepSeek necesite mantener contexto entre mensajes
- Con `--session`: tareas que se extienden por horas/dias con contexto persistente
- Con `--transfer-from`: conversaciones que necesitan contexto de otro chat

## Tips

- Cada mensaje acumula historial: DeepSeek recuerda TODO lo anterior.
- Skills, memoria y knowledge se inyectan automaticamente como Phase 2 (trackeado per-sesion).
- Usa mensajes cortos y precisos para cada turno — no repitas contexto.
- Para tareas simples de un solo turno, usa `/deepseek-code:delegate`.
- Usa `--session-digest` para decidir a cual chat enviar mensajes.
- Usa `--transfer-from` para compartir conocimiento entre chats.
