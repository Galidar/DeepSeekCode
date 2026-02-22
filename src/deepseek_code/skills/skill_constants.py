"""Constantes del sistema de inyeccion de skills.

Contiene mapas de keywords, tiers de conocimiento y presupuestos de tokens.
Separado de skill_injector.py para respetar el limite de 400 lineas por archivo.

Sistema adaptivo: los budgets escalan con la complejidad de la tarea.
"""

# === CORE SKILLS (inyeccion CONDICIONAL, ya no obligatoria) ===
# Solo common-errors-reference tiene valor practico real.
# Los otros son conocimiento que DeepSeek ya posee inherentemente.
CORE_SKILLS = [
    "programming-foundations",
    "data-structures-algorithms",
    "common-errors-reference",
]

# Skill que se inyecta solo si SurgicalMemory reporta errores recurrentes
ERROR_REFERENCE_SKILL = "common-errors-reference"

# === Presupuestos ADAPTATIVOS por nivel de tarea ===
# Indexados por string del TaskLevel (evita import circular)
ADAPTIVE_BUDGETS = {
    "chat":         {"core": 0, "domain": 0,     "specialist": 0,     "total": 0},
    "simple":       {"core": 0, "domain": 0,     "specialist": 0,     "total": 0},
    "code_simple":  {"core": 0, "domain": 10000, "specialist": 0,     "total": 10000},
    "code_complex": {"core": 0, "domain": 30000, "specialist": 10000, "total": 40000},
    "delegation":   {"core": 0, "domain": 45000, "specialist": 20000, "total": 80000},
}

# === Presupuestos legacy (retrocompatibilidad) ===
DELEGATE_TOKEN_BUDGET = ADAPTIVE_BUDGETS["delegation"]

INTERACTIVE_TOKEN_BUDGET = {
    "web": 80000,   # Modo web (1M tokens contexto) — generoso
    "api": 12000,   # Modo API (128K tokens contexto) — conservador
}

# === Mapa de keywords -> nombres de skills (.skill sin extension) ===
# Cada skill tiene keywords que la activan por relevancia
SKILL_KEYWORD_MAP = {
    # --- Skills originales (18) ---
    "advanced-coding": [
        "codigo", "code", "programar", "funcion", "clase", "patron",
        "pattern", "refactor", "arquitectura", "modular", "clean",
        "profesional", "calidad", "debug", "error handling",
    ],
    "web-audio-api": [
        "audio", "sonido", "sound", "musica", "music", "sfx",
        "webaudio", "audiocontext", "oscillator", "gain",
        "frequency", "beep", "tone",
    ],
    "sounds-on-the-web": [
        "audio", "sonido", "sound", "musica", "music",
        "mp3", "ogg", "wav", "efectos sonido",
    ],
    "modern-javascript-patterns": [
        "javascript", "js", "es6", "async", "await", "promise",
        "map", "filter", "reduce", "destructuring", "spread",
        "module", "import", "export", "class",
    ],
    "procedural-generation": [
        "procedural", "generacion", "random", "noise", "perlin",
        "terreno", "terrain", "dungeon", "maze", "laberinto",
        "mapa", "level generation", "wave function",
    ],
    "character-sprite": [
        "sprite", "spritesheet", "animacion", "animation",
        "frame", "pixel", "tileset", "atlas",
    ],
    "claude-delegate": [
        "delegar", "delegate", "claude", "template", "todo",
        "split", "divide", "colaborar",
    ],
    "project-architecture": [
        "arquitectura", "estructura", "proyecto", "carpeta",
        "modulo", "organizacion", "monorepo", "workspace",
    ],
    "custom-algorithmic-art": [
        "arte", "art", "algoritmico", "generativo", "particula",
        "particle", "efecto visual", "shader", "gradient",
    ],
    "interface-design": [
        "interfaz", "interface", "ui", "ux", "menu", "boton",
        "button", "formulario", "form", "layout", "responsive",
    ],
    "ui-ux-pro-max": [
        "ui", "ux", "diseno", "design", "interfaz", "interface",
        "user experience", "usabilidad", "accesibilidad",
    ],
    "server-management": [
        "servidor", "server", "deploy", "hosting", "nginx",
        "docker", "pm2", "systemd", "ssl", "https",
    ],
    "code-review-excellence": [
        "review", "revision", "code review", "calidad",
        "mejora", "optimizar", "optimize", "refactor",
    ],
    "java-spring-boot": [
        "java", "spring", "boot", "maven", "gradle",
        "jpa", "hibernate", "rest api", "microservicio",
    ],
    "vercel-react-best-practices": [
        "react", "next", "nextjs", "vercel", "component",
        "hook", "useState", "useEffect", "jsx", "tsx",
    ],
    "server-side-rendering": [
        "ssr", "server side", "hydration", "seo",
        "renderizado", "pre-render", "static",
    ],
    "webgpu": [
        "webgpu", "gpu", "compute", "shader", "wgsl",
        "render pipeline", "buffer", "texture gpu",
    ],
    "threejs-shaders": [
        "three", "threejs", "3d", "shader", "glsl",
        "material", "geometry", "scene", "camera",
    ],
    # --- Skills previamente huerfanas (19) - ahora mapeadas ---
    "apollo-mcp-server": [
        "graphql", "apollo", "query", "mutation", "schema", "resolver",
    ],
    "audiocraft-audio-generation": [
        "music generation", "audiocraft", "meta audio",
        "generacion musical", "ai music",
    ],
    "audit-website": [
        "audit", "lighthouse", "performance audit", "seo audit",
        "accesibilidad", "a11y", "web vitals",
    ],
    "building-native-ui": [
        "native", "nativo", "desktop app", "electron",
        "tauri", "widget", "ventana",
    ],
    "chat-ui": [
        "chat", "mensaje", "message", "conversacion",
        "chatbot", "bubble", "messenger",
    ],
    "cloudflare-mcp-server": [
        "cloudflare", "workers", "kv store", "r2",
        "pages", "cdn", "edge computing",
    ],
    "create-design-system-rules": [
        "design system", "tokens", "theme", "design tokens",
        "estilo global", "branding",
    ],
    "custom-web-artifacts-builder": [
        "artifact", "widget", "embed", "iframe",
        "componente web", "web component",
    ],
    "document-chat-interface": [
        "documento", "document", "pdf", "chat document",
        "rag", "knowledge base",
    ],
    "json-canvas": [
        "json canvas", "obsidian", "canvas", "nodo",
        "node graph", "flow diagram",
    ],
    "launch-strategy": [
        "launch", "lanzamiento", "marketing",
        "estrategia", "go to market", "product launch",
    ],
    "manaseed-integration": [
        "manaseed", "rpg maker", "pixel art rpg",
        "tileset rpg", "mana seed",
    ],
    "official-skill-creator": [
        "crear skill", "create skill", "skill yaml",
        "workflow skill", "definir skill",
    ],
    "remotion-best-practices": [
        "remotion", "video", "render video",
        "animation video", "video programatico",
    ],
    "rivetkit-client-javascript": [
        "rivet", "state chart", "visual scripting",
        "rivetkit", "node editor",
    ],
    "skill-judge": [
        "evaluar skill", "evaluate", "judge skill",
        "quality skill", "calidad skill",
    ],
    "ue57-rhi-api-migration": [
        "unreal", "ue5", "ue4", "rhi",
        "graphics api", "directx", "vulkan unreal",
    ],
    "web-design-guidelines": [
        "web design", "diseno web", "landing page",
        "hero section", "cta", "above the fold",
    ],
    "webgpu-threejs-tsl": [
        "tsl", "three shader language", "webgpu three",
        "shader node", "node material",
    ],
    # --- Skills nuevas de conocimiento fundamental ---
    "canvas-2d-reference": [
        "canvas", "2d", "dibujar", "draw", "fillRect",
        "beginPath", "ctx", "getContext", "render",
    ],
    "math-foundations": [
        "matematica", "math", "algebra", "vector", "matrix",
        "curva", "interpolacion", "noise", "perlin", "trigonometria",
        "bezier", "easing",
    ],
    "physics-simulation": [
        "fisica", "physics", "colision", "collision", "gravity",
        "rigid body", "particula", "velocity", "verlet",
        "steering", "rebote", "bounce",
    ],
    "game-genre-patterns": [
        "shmup", "shooter", "platformer", "tower defense",
        "rpg", "roguelike", "puzzle", "endless runner",
        "fighting game", "rts",
    ],
    "typescript-advanced": [
        "typescript", "ts", "tipos", "types", "generic",
        "interface", "type guard", "utility type", "infer",
        "discriminated union",
    ],
    "database-patterns": [
        "database", "db", "sql", "mongo", "mongodb", "redis",
        "orm", "query", "schema", "migration", "index",
        "aggregation", "transaction",
    ],
    "security-auth-patterns": [
        "seguridad", "security", "auth", "jwt", "oauth",
        "cors", "csrf", "xss", "password", "encrypt",
        "token", "login", "session",
    ],
    "backend-node-patterns": [
        "node", "express", "fastify", "backend", "api",
        "rest", "endpoint", "middleware", "server",
        "websocket", "http", "route",
    ],
    "css-modern-patterns": [
        "css", "tailwind", "flexbox", "grid", "responsive",
        "layout", "estilo", "style", "animation css",
        "media query", "container query",
    ],
}

# Keywords que indican contexto de juegos (activa bonus para GAME_SKILLS)
GAME_KEYWORDS = [
    "juego", "game", "shmup", "shooter", "plataforma", "platformer",
    "canvas", "sprite", "enemigo", "enemy", "player", "jugador",
    "colision", "collision", "bala", "bullet", "power-up", "powerup",
    "boss", "wave", "nivel", "level", "puntuacion", "score",
    "nave", "ship", "explosion", "particula", "invader", "asteroid",
]

# Skills que reciben bonus en contexto de juegos
GAME_SKILLS = [
    "advanced-coding",
    "web-audio-api",
    "procedural-generation",
    "canvas-2d-reference",
    "physics-simulation",
    "game-genre-patterns",
]
