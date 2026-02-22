---
description: Run N parallel DeepSeek instances with differentiated roles (generator, reviewer, tester)
argument-hint: <description of the complex task>
---

Eres Claude Code y vas a ejecutar una tarea compleja usando multiples instancias de DeepSeek Code en paralelo, cada una con un rol diferenciado.

Carga y sigue todas las guias de la skill `deepseek-code-mastery` de este plugin para entender el sistema completo.

**Tu tarea:** Basandote en la solicitud del usuario "$ARGUMENTS", construye y ejecuta el comando multi-sesion correcto.

## Proceso

1. **Analiza la complejidad**: Si la tarea es simple, usa `/deepseek-code:delegate` en su lugar.

2. **Elige el preset de roles**:
   - `generate-review` (default): Un generador + un reviewer. Ideal para codigo que necesita validacion.
   - `full-pipeline`: Generador + reviewer + tester. Para codigo critico.
   - `dual-generator`: Dos generadores independientes. Para explorar enfoques alternativos.
   - `specialist-pair`: Dos especialistas en dominios diferentes. Para fullstack.

3. **Elige el modo de ejecucion**:
   - **Paralelo** (default): Todas las instancias corren simultaneamente.
   - **Pipeline** (`--pipeline`): Secuencial. Output de N se pasa como contexto a N+1.

4. **Construye el comando**:
   ```bash
   python run.py --multi "TAREA" [--template FILE] --roles PRESET [--instances N] [--pipeline] --json
   ```

   IMPORTANTE: Ejecuta desde el directorio raiz del proyecto DeepSeek Code.

5. **Ejecuta via Bash** y captura el JSON de respuesta.

6. **Interpreta el resultado**:
   - `multi.results[]` contiene la respuesta de cada instancia con su rol
   - `review` contiene issues encontrados por el reviewer (si aplica)
   - `validation` contiene resultado de validacion contra template
   - El response principal es del generador (o ultimo en pipeline)

## Presets

| Preset | Instancias | Uso | Costo |
|--------|-----------|-----|-------|
| generate-review | 2 | Codigo + validacion | 2x PoW |
| full-pipeline | 3 | Codigo + review + tests | 3x PoW |
| dual-generator | 2 | Explorar alternativas | 2x PoW |
| specialist-pair | 2 | Frontend + Backend | 2x PoW |

## Tips

- Cada instancia consume una sesion DeepSeek independiente (PoW challenge + chat).
- Para tareas simples, `/deepseek-code:delegate` es mas eficiente.
- Pipeline mode es ideal para: generate -> review -> fix.
- El reviewer reporta bugs reales, no sugerencias de estilo.
