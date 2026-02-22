---
description: Iterative multi-turn dialogue with DeepSeek Code (shared quantum thinking)
argument-hint: <messages separated by | or conversation description>
---

Eres Claude Code y vas a mantener un dialogo iterativo multi-turno con DeepSeek Code, tu subordinado.

Carga y sigue todas las guias de la skill `deepseek-code-mastery` de este plugin.

**Tu tarea:** Basandote en "$ARGUMENTS", construye y ejecuta una conversacion multi-turno con DeepSeek.

## Proceso

1. **Prepara los mensajes**: Divide la tarea en turnos logicos de conversacion.

2. **Crea el JSON de entrada**:
   ```json
   {
     "system": "system prompt opcional",
     "messages": ["primer mensaje", "segundo mensaje", "tercer mensaje"]
   }
   ```

3. **Ejecuta el comando**:
   ```bash
   # Opcion A: Mensaje unico
   python run.py --converse "MENSAJE" --json

   # Opcion B: Multiples turnos via archivo
   echo '{"messages":["msg1","msg2"]}' > /tmp/converse.json
   python run.py --converse-file /tmp/converse.json --json

   # Opcion C: Via stdin
   echo '{"messages":["msg1","msg2"]}' | python run.py --converse --json
   ```

   IMPORTANTE: Ejecuta desde el directorio raiz del proyecto DeepSeek Code (donde esta `run.py`). Detectalo con: `git rev-parse --show-toplevel` o busca `run.py` en la ruta de instalacion del usuario.

4. **Interpreta el resultado**:
   - `success: true` -> Usa `response` (ultima respuesta) y `turns` (historial completo)
   - Cada turno incluye `user`, `assistant`, `duration_s`, `response_tokens`
   - `token_usage` muestra consumo total del dialogo

5. **Aplica el resultado**: Escribe el codigo generado en los archivos del proyecto.

## Cuando Usar Converse

- Refinamiento iterativo: "crea la base" -> "ahora agrega validacion" -> "optimiza el rendimiento"
- Debugging colaborativo: enviar error -> recibir diagnostico -> aplicar fix -> verificar
- Diseno progresivo: construir una feature paso a paso con feedback entre turnos
- Cualquier tarea donde necesites que DeepSeek mantenga contexto entre mensajes

## Tips

- Cada mensaje acumula historial: DeepSeek recuerda TODO lo anterior.
- El system prompt se enriquece con SurgicalMemory + GlobalMemory + Skills automaticamente.
- Usa mensajes cortos y precisos para cada turno — no repitas contexto.
- Para tareas simples de un solo turno, usa `/deepseek-code:delegate` en vez de converse.
