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

## Proceso

1. **Analiza la tarea** y determina los dos angulos/perspectivas mas utiles.

2. **Elige angulos**:
   - Frontend + Backend: `--quantum-angles "frontend,backend"`
   - Logica + Visual: `--quantum-angles "logica,visual"` o `--quantum-angles "logica,render"`
   - API + Database: `--quantum-angles "api,database"`
   - Core + UI: `--quantum-angles "core,ui"`
   - O dejalo automatico (sin `--quantum-angles`) para deteccion inteligente

3. **Construye el comando**:
   ```bash
   python run.py --quantum "DESCRIPCION_TAREA" [--template FILE] [--quantum-angles "a,b"] --json
   ```

   IMPORTANTE: Ejecuta desde el directorio raiz del proyecto DeepSeek Code (donde esta `run.py`). Detectalo con: `git rev-parse --show-toplevel` o busca `run.py` en la ruta de instalacion del usuario.

4. **Ejecuta via Bash** y procesa el resultado mergeado.

5. **Aplica el codigo**: El resultado es el merge de ambas perspectivas. Revisalo y aplica al proyecto.

## Tips

- El merge usa 3 estrategias en cascada: template-guided -> function-based -> raw
- Si el resultado no es satisfactorio, puedes re-ejecutar con `--delegate --feedback` para corregir
- No uses quantum para tareas simples: el overhead no vale la pena para <200 lineas
