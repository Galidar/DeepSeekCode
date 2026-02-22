"""Carga y valida definiciones de skills desde archivos YAML y .skill (ZIP)."""

import yaml
import zipfile
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class SkillParameter:
    """Parametro de entrada de un skill."""
    name: str
    description: str = ""
    required: bool = True
    default: Optional[str] = None


@dataclass
class SkillStep:
    """Un paso individual dentro de un skill."""
    id: str
    tool: str
    args: dict
    description: str = ""
    optional: bool = False


@dataclass
class SkillDefinition:
    """Definicion completa de un skill (workflow ejecutable)."""
    name: str
    description: str
    parameters: List[SkillParameter]
    steps: List[SkillStep]
    output: str = ""
    version: str = "1.0"
    author: str = ""
    skill_type: str = "workflow"


@dataclass
class KnowledgeSkill:
    """Skill de conocimiento: contiene documentacion que se inyecta como contexto."""
    name: str
    description: str
    content: str  # Markdown completo
    skill_type: str = "knowledge"


class SkillLoader:
    """Carga skills desde archivos YAML y .skill (ZIP).

    Incluye cache interno para evitar recargar skills frecuentes (ej: core).
    """

    def __init__(self, skills_dir: str):
        self.skills_dir = Path(skills_dir)
        self._cache: Dict[str, 'KnowledgeSkill'] = {}

    def load_all(self) -> dict:
        """Carga todos los skills del directorio (YAML workflows + .skill knowledge)."""
        skills = {}
        if not self.skills_dir.exists():
            return skills
        for f in self.skills_dir.glob("*.yaml"):
            try:
                skill = self._load_file(f)
                skills[skill.name] = skill
            except Exception as e:
                print(f"Error cargando skill {f.name}: {e}")
        for f in self.skills_dir.glob("*.yml"):
            try:
                skill = self._load_file(f)
                if skill.name not in skills:
                    skills[skill.name] = skill
            except Exception as e:
                print(f"Error cargando skill {f.name}: {e}")
        for f in self.skills_dir.glob("*.skill"):
            try:
                skill = self._load_skill_package(f)
                if skill and skill.name not in skills:
                    skills[skill.name] = skill
            except Exception as e:
                print(f"Error cargando skill package {f.name}: {e}")
        return skills

    def load_one(self, name: str):
        """Carga un skill especifico por nombre (con cache para .skill)."""
        # Cache hit para knowledge skills
        if name in self._cache:
            return self._cache[name]
        for ext in (".yaml", ".yml"):
            path = self.skills_dir / f"{name}{ext}"
            if path.exists():
                return self._load_file(path)
        # Buscar como .skill package
        path = self.skills_dir / f"{name}.skill"
        if path.exists():
            skill = self._load_skill_package(path)
            if skill:
                self._cache[name] = skill
            return skill
        return None

    def load_multiple(self, names: List[str]) -> List['KnowledgeSkill']:
        """Carga multiples skills por nombre (batch eficiente con cache)."""
        results = []
        for name in names:
            skill = self.load_one(name)
            if skill and isinstance(skill, KnowledgeSkill):
                results.append(skill)
        return results

    def _load_skill_package(self, path: Path) -> Optional[KnowledgeSkill]:
        """Carga un archivo .skill (ZIP con SKILL.md dentro)."""
        if not zipfile.is_zipfile(path):
            return None
        with zipfile.ZipFile(path, 'r') as z:
            # Buscar SKILL.md dentro del ZIP
            skill_md = None
            for name in z.namelist():
                if name.endswith('SKILL.md'):
                    skill_md = name
                    break
            if not skill_md:
                return None
            with z.open(skill_md) as f:
                content = f.read().decode('utf-8')
        # Parsear frontmatter YAML del markdown
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                body = parts[2].strip()
                return KnowledgeSkill(
                    name=frontmatter.get('name', path.stem),
                    description=frontmatter.get('description', ''),
                    content=body
                )
        # Sin frontmatter, usar nombre del archivo
        return KnowledgeSkill(
            name=path.stem,
            description='',
            content=content
        )

    def _load_file(self, path: Path) -> SkillDefinition:
        """Carga y valida un archivo YAML de skill."""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"El archivo {path.name} no tiene formato YAML valido")

        # Campos requeridos
        name = data.get("name")
        if not name:
            raise ValueError(f"El skill en {path.name} no tiene campo 'name'")

        description = data.get("description", "")
        steps_data = data.get("steps", [])
        if not steps_data:
            raise ValueError(f"El skill '{name}' no tiene pasos definidos")

        # Parsear parametros
        params = []
        for p in data.get("parameters", []):
            if isinstance(p, str):
                params.append(SkillParameter(name=p))
            elif isinstance(p, dict):
                params.append(SkillParameter(
                    name=p["name"],
                    description=p.get("description", ""),
                    required=p.get("required", True),
                    default=p.get("default")
                ))

        # Parsear pasos
        steps = []
        for s in steps_data:
            if not isinstance(s, dict):
                raise ValueError(f"Paso invalido en skill '{name}': {s}")
            step_id = s.get("id", f"step_{len(steps) + 1}")
            tool = s.get("tool")
            if not tool:
                raise ValueError(f"Paso '{step_id}' en skill '{name}' no tiene campo 'tool'")
            steps.append(SkillStep(
                id=step_id,
                tool=tool,
                args=s.get("args", {}),
                description=s.get("description", ""),
                optional=s.get("optional", False)
            ))

        return SkillDefinition(
            name=name,
            description=description,
            parameters=params,
            steps=steps,
            output=data.get("output", ""),
            version=data.get("version", "1.0"),
            author=data.get("author", "")
        )
