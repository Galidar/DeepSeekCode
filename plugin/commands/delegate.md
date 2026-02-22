---
description: Delegate a code task to DeepSeek Code using oneshot mode
argument-hint: <description of the task to delegate>
---

Eres Claude Code y vas a delegar una tarea de generacion de codigo a DeepSeek Code, tu subordinado especialista en codigo.

Carga y sigue todas las guias de la skill `deepseek-code-mastery` de este plugin para entender el sistema completo.

**Tu tarea:** Basandote en la solicitud del usuario "$ARGUMENTS", construye y ejecuta el comando de delegacion correcto.

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

## Auto-Continuacion

Si DeepSeek trunca su respuesta, el sistema automaticamente detecta el truncamiento y envia "continua" hasta 3 veces. Las partes se concatenan. Es transparente — save_response recibe la respuesta completa.

## Tips

- La tarea debe ser PRECISA y DESCRIPTIVA. "crea un endpoint" es malo. "crea endpoint POST /api/users con validacion Zod de email+name+password, hash bcrypt, y respuesta 201 con user sin password" es bueno.
- DeepSeek responde SOLO codigo, sin markdown ni explicaciones.
- Si el resultado es muy grande para una delegacion, considera `/deepseek-code:multi-step` o `/deepseek-code:quantum`.
- Para refinamiento iterativo, usa `/deepseek-code:converse`.
