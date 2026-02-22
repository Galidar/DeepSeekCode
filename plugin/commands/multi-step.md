---
description: Execute a multi-step plan with DeepSeek Code for multi-file tasks
argument-hint: <description of the feature requiring multiple files>
---

Eres Claude Code y vas a crear y ejecutar un plan multi-paso con DeepSeek Code para una feature que requiere generar multiples archivos.

Carga y sigue todas las guias de la skill `deepseek-code-mastery` de este plugin.

**Tu tarea:** Basandote en la solicitud del usuario "$ARGUMENTS", crea un plan JSON y ejecutalo.

## Proceso Token-Eficiente

**REGLA CRITICA: Nunca uses Write para guardar codigo generado. Siempre usa pipe directo a disco.**

### Fase 1: Planifica

1. **Analiza la feature** y divide en pasos logicos (1 paso = 1 archivo o componente).
2. **Identifica dependencias**: Si paso B necesita resultado de paso A -> `context_from: ["A"]`.
3. **Identifica paralelismo**: Pasos independientes -> mismo `parallel_group`.

### Fase 2: Crea y ejecuta el plan

1. **Escribe el plan JSON** como archivo temporal:

```json
{
  "steps": [
    {
      "id": "paso-descriptivo",
      "task": "descripcion precisa de que generar",
      "template": "ruta/al/template.ext",
      "context_from": ["id-de-paso-previo"],
      "validate": true,
      "max_retries": 2,
      "parallel_group": "nombre-grupo",
      "dual_mode": false
    }
  ]
}
```

2. **Ejecuta con pipe directo**:
```bash
cd DEEPSEEK_DIR && python run.py --multi-step /tmp/plan.json --json 2>/dev/null | \
    python -m deepseek_code.tools.save_response --split --dir "RUTA/PROYECTO/" --preview 3
```

IMPORTANTE: Ejecuta desde el directorio raiz del proyecto DeepSeek Code (donde esta `run.py`).

### Fase 3: Supervisa y corrige

1. **Lee la metadata** — cuantos archivos se generaron, cuales pasos tuvieron exito.
2. **Verifica** cada archivo leyendo solo las primeras lineas.
3. **Corrige** bugs puntuales con Edit (ediciones quirurgicas).

## Ejemplo de Plan

Para crear un modulo CRUD completo:

```json
{
  "steps": [
    {"id": "model", "task": "modelo TypeScript de Producto con validacion Zod"},
    {"id": "routes", "task": "endpoints Express CRUD para Producto", "context_from": ["model"]},
    {"id": "test-unit", "task": "tests unitarios del modelo", "context_from": ["model"], "parallel_group": "tests"},
    {"id": "test-api", "task": "tests de integracion de API", "context_from": ["routes"], "parallel_group": "tests"}
  ]
}
```

## Tips

- Pasos con `dual_mode: true` usan Quantum Bridge (mejor para pasos complejos)
- `parallel_group` acelera la ejecucion: pasos del mismo grupo corren simultaneamente
- `context_from` inyecta el codigo generado en pasos previos como referencia
- Maximo recomendado: 6-8 pasos por plan
