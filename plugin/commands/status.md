---
description: Verify that DeepSeek Code is properly configured and ready to use
argument-hint:
---

You are Claude Code and you will verify that the DeepSeek Code system is properly configured and ready to delegate work.

Load the `deepseek-code-mastery` skill from this plugin for reference.

## Path Detection

Before running the checks, detect the system paths:

1. **DEEPSEEK_DIR** (project directory): Look for `run.py` in possible locations. Try in order:
   - Environment variable `DEEPSEEK_CODE_DIR` if it exists
   - Search for `run.py` going up from the current directory
   - Common paths: `~/Desktop/AI/DeepSeekMCP`, `~/DeepSeekMCP`, `~/DeepSeek-Code`

2. **APPDATA_DIR** (configuration):
   - Windows: `%APPDATA%\DeepSeek-Code\`
   - Linux/macOS: `~/.config/DeepSeek-Code/`

Detect both paths and use them in all following commands.

## Checks to Run

Run the following commands via Bash (replacing DEEPSEEK_DIR and APPDATA_DIR with detected paths) and report the status of each:

### 1. Project Exists
```bash
ls "DEEPSEEK_DIR/run.py"
```
The entry point must exist.

### 2. Configuration
```bash
python -c "import json, os; appdata=os.path.join(os.environ.get('APPDATA', os.path.expanduser('~/.config')), 'DeepSeek-Code'); c=json.load(open(os.path.join(appdata, 'config.json'))); print(f'Modo: {\"web\" if c.get(\"bearer_token\") else \"api\" if c.get(\"api_key\") else \"sin-credenciales\"}'); print(f'Skills dir: {c.get(\"skills_dir\", \"default\")}'); print(f'Serena: {c.get(\"serena_enabled\", True)}')"
```

### 3. Available Skills
```bash
cd "DEEPSEEK_DIR" && python -c "import sys; sys.path.insert(0,'src'); from deepseek_code.skills.loader import SkillLoader; loader=SkillLoader('skills'); skills=loader.load_all(); print(f'Skills: {len(skills)} ({len([s for s in skills if not hasattr(s,\"steps\")])} knowledge + {len([s for s in skills if hasattr(s,\"steps\")])} workflows)')"
```

### 4. Core Skills (Tier 1)
```bash
cd "DEEPSEEK_DIR" && python -c "import sys; sys.path.insert(0,'src'); from deepseek_code.skills.loader import SkillLoader; loader=SkillLoader('skills'); [print(f'  {s.name}: {len(s.content)} chars') for s in loader.load_multiple(['programming-foundations','data-structures-algorithms','common-errors-reference'])]"
```

### 5. Quick Delegation Test
```bash
cd "DEEPSEEK_DIR" && python run.py --delegate "funcion JavaScript: fibonacci recursivo con memoizacion" --json 2>nul
```

## Report

Present results in a clear format:
- OK/FAIL for each check
- Whether valid credentials exist
- How many skills are available
- Whether the delegation test worked
- Recommendations if anything fails
