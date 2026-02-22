---
description: Execute a multi-step plan with DeepSeek Code for multi-file tasks
argument-hint: <description of the feature requiring multiple files>
---

Eres Claude Code y vas a crear y ejecutar un plan multi-paso con DeepSeek Code para una feature que requiere generar multiples archivos.

Carga y sigue todas las guias de la skill `deepseek-code-mastery` de este plugin.

**Tu tarea:** Basandote en la solicitud del usuario "$ARGUMENTS", crea un plan JSON y ejecutalo.

## Proceso

1. **Analiza la feature** y divide en pasos logicos (1 paso = 1 archivo o componente).

2. **Identifica dependencias**: Si el paso B necesita el resultado del paso A, usa `context_from: ["A"]`.

3. **Identifica paralelismo**: Pasos independientes pueden ir en el mismo `parallel_group`.

4. **Crea el plan JSON** como archivo temporal:

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

5. **Escribe el plan** a un archivo temporal (ej: `/tmp/plan.json`).

6. **Ejecuta**:
   ```bash
   python run.py --multi-step /tmp/plan.json --json
   ```

   IMPORTANTE: Ejecuta desde el directorio raiz del proyecto DeepSeek Code (donde esta `run.py`). Detectalo con: `git rev-parse --show-toplevel` o busca `run.py` en la ruta de instalacion del usuario.

7. **Procesa resultados**: El JSON de respuesta tiene un array con el resultado de cada paso.

8. **Aplica los archivos generados** al proyecto del usuario.

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
