---
description: Dual parallel delegation with Quantum Bridge for complex tasks
argument-hint: <complex task that benefits from two perspectives>
---

Eres Claude Code y vas a usar el Quantum Bridge de DeepSeek Code para delegar una tarea compleja con dos perspectivas paralelas.

Carga y sigue todas las guias de la skill `deepseek-code-mastery` de este plugin.

**Tu tarea:** Basandote en la solicitud del usuario "$ARGUMENTS", construye y ejecuta una delegacion quantum dual.

## Cuando Usar Quantum

- La tarea tiene multiples aspectos (frontend+backend, logica+visual, core+ui)
- El template tiene muchos TODOs (>8) y hay riesgo de truncamiento
- Quieres mejor calidad combinando dos perspectivas

## Proceso Token-Eficiente

**REGLA CRITICA: Nunca uses Write para guardar el codigo. Siempre usa pipe directo a disco.**

### Fase 1: Analiza y elige angulos

1. **Analiza la tarea** y determina los dos angulos mas utiles.
2. **Elige angulos**:
   - Frontend + Backend: `--quantum-angles "frontend,backend"`
   - Logica + Visual: `--quantum-angles "logica,visual"`
   - API + Database: `--quantum-angles "api,database"`
   - Core + UI: `--quantum-angles "core,ui"`
   - O dejalo automatico (sin `--quantum-angles`) para deteccion inteligente

### Fase 2: Ejecuta con pipe directo

**Para un solo archivo mergeado:**
```bash
cd DEEPSEEK_DIR && python run.py --quantum "TAREA" [--quantum-angles "a,b"] --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --output "RUTA/archivo.ext" --preview 5
```

**Para proyecto multi-archivo:**
```bash
cd DEEPSEEK_DIR && python run.py --quantum "TAREA" [--quantum-angles "a,b"] --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --split --dir "RUTA/PROYECTO/" --preview 5
```

IMPORTANTE: Ejecuta desde el directorio raiz del proyecto DeepSeek Code (donde esta `run.py`).

### Fase 3: Supervisa y corrige

1. **Lee la metadata** (success, lines, files_saved, duration_s).
2. **Verifica** con Read solo las primeras lineas si necesario.
3. **Corrige** bugs con Edit (ediciones quirurgicas, nunca reescribir).

## Tips

- El merge usa 3 estrategias en cascada: template-guided -> function-based -> raw
- Si el resultado no es satisfactorio, re-ejecuta con `--delegate --feedback`
- No uses quantum para tareas simples: el overhead no vale la pena para <200 lineas
