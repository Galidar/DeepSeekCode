#!/usr/bin/env python3
"""Punto de entrada para el ejecutable de DeepSeek-Code."""

import sys
import os

# Añadir el directorio src al path para que las importaciones funcionen
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from cli.main import main

if __name__ == '__main__':
    main()
