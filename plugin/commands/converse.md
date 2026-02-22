---
description: Iterative multi-turn dialogue with DeepSeek Code (shared quantum thinking)
argument-hint: <messages separated by | or conversation description>
---

Eres Claude Code y vas a mantener un dialogo iterativo multi-turno con DeepSeek Code, tu subordinado.

Carga y sigue todas las guias de la skill `deepseek-code-mastery` de este plugin.

**Tu tarea:** Basandote en "$ARGUMENTS", construye y ejecuta una conversacion multi-turno con DeepSeek.

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

## Cuando Usar Converse

- Refinamiento iterativo: "crea la base" -> "ahora agrega validacion" -> "optimiza"
- Debugging colaborativo: enviar error -> diagnostico -> fix -> verificar
- Diseno progresivo: construir feature paso a paso con feedback entre turnos
- Cualquier tarea donde DeepSeek necesite mantener contexto entre mensajes

## Tips

- Cada mensaje acumula historial: DeepSeek recuerda TODO lo anterior.
- El system prompt se enriquece con SurgicalMemory + GlobalMemory + Skills automaticamente.
- Usa mensajes cortos y precisos para cada turno — no repitas contexto.
- Para tareas simples de un solo turno, usa `/deepseek-code:delegate`.
