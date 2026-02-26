#!/usr/bin/env python3
"""Punto de entrada para el ejecutable de DeepSeek-Code."""

import sys
import os

# Forzar stderr line-buffered para que los diagnosticos SSE y logs
# del agente se vean en tiempo real, incluso cuando stderr esta piped.
# Sin esto, print(..., file=sys.stderr) se bufferiza completamente
# en pipes y no se ve nada hasta que el proceso termina.
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

# Añadir el directorio src al path para que las importaciones funcionen
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from cli.main import main

if __name__ == '__main__':
    main()
