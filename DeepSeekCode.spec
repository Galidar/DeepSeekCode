# -*- mode: python ; coding: utf-8 -*-
# DeepSeek Code v4.2.0 — Certified build spec
# All modules: cli (22), deepseek_code (68), external deps
from PyInstaller.utils.hooks import collect_all

datas = [('src', 'src'), ('skills', 'skills')]
binaries = []
hiddenimports = [
    # --- cli ---
    'cli', 'cli.main', 'cli.commands', 'cli.commands_helpers',
    'cli.config_loader', 'cli.i18n', 'cli.onboarding', 'cli.ui_theme',
    'cli.oneshot', 'cli.oneshot_helpers', 'cli.secure_config',
    'cli.delegate_validator', 'cli.bridge_utils',
    'cli.converse', 'cli.multi_step', 'cli.multi_step_helpers',
    'cli.multi_runner',
    'cli.quantum_runner', 'cli.quantum_helpers', 'cli.collaboration',
    # --- deepseek_code core ---
    'deepseek_code',
    'deepseek_code.tools', 'deepseek_code.tools.filesystem', 'deepseek_code.tools.file_editor',
    'deepseek_code.tools.shell', 'deepseek_code.tools.memory_tool',
    'deepseek_code.tools.key_manager', 'deepseek_code.tools.archive_tool', 'deepseek_code.tools.file_utils',
    'deepseek_code.tools.save_response',
    'deepseek_code.client', 'deepseek_code.client.deepseek_client',
    'deepseek_code.client.web_session', 'deepseek_code.client.web_tool_caller',
    'deepseek_code.client.context_manager',
    'deepseek_code.client.api_caller', 'deepseek_code.client.template_chunker',
    'deepseek_code.client.task_classifier', 'deepseek_code.client.prompt_builder',
    'deepseek_code.client.ai_protocol', 'deepseek_code.client.session_chat',
    'deepseek_code.sessions', 'deepseek_code.sessions.session_store',
    'deepseek_code.sessions.session_namespace', 'deepseek_code.sessions.session_orchestrator',
    'deepseek_code.sessions.summary_engine', 'deepseek_code.sessions.knowledge_transfer',
    'cli.session_commands', 'cli.chat_manager',
    'deepseek_code.server', 'deepseek_code.server.protocol', 'deepseek_code.server.tool',
    'deepseek_code.security', 'deepseek_code.security.sandbox',
    'deepseek_code.auth', 'deepseek_code.auth.web_login',
    'deepseek_code.auth.session_manager', 'deepseek_code.auth.token_monitor',
    'deepseek_code.auth.account_manager',
    'deepseek_code.agent', 'deepseek_code.agent.engine', 'deepseek_code.agent.logger',
    'deepseek_code.agent.prompts',
    'deepseek_code.skills', 'deepseek_code.skills.loader', 'deepseek_code.skills.runner',
    'deepseek_code.skills.skill_injector', 'deepseek_code.skills.skill_constants',
    'deepseek_code.skills.semantic_skill_index',
    'deepseek_code.skills.skill_catalog', 'deepseek_code.skills.skill_negotiation',
    'deepseek_code.serena', 'deepseek_code.serena.client', 'deepseek_code.serena.proxy_tool',
    'deepseek_code.serena.manager', 'deepseek_code.serena.native_tools',
    'deepseek_code.serena.code_patterns',
    'deepseek_code.quantum', 'deepseek_code.quantum.dual_session',
    'deepseek_code.quantum.multi_session', 'deepseek_code.quantum.roles',
    'deepseek_code.quantum.strategy_advisor',
    'deepseek_code.quantum.angle_detector', 'deepseek_code.quantum.merge_engine',
    'deepseek_code.quantum.merge_helpers',
    'deepseek_code.surgical', 'deepseek_code.surgical.store',
    'deepseek_code.surgical.collector', 'deepseek_code.surgical.injector',
    'deepseek_code.surgical.learner', 'deepseek_code.surgical.integration',
    'deepseek_code.global_memory', 'deepseek_code.global_memory.global_store',
    'deepseek_code.global_memory.global_learner', 'deepseek_code.global_memory.global_injector',
    'deepseek_code.global_memory.global_integration',
    'deepseek_code.intelligence', 'deepseek_code.intelligence.debugger',
    'deepseek_code.intelligence.shadow_learner', 'deepseek_code.intelligence.git_intel',
    'deepseek_code.intelligence.requirements_parser', 'deepseek_code.intelligence.predictor',
    'deepseek_code.intelligence.predictor_bayesian', 'deepseek_code.intelligence.semantic_engine',
    'deepseek_code.intelligence.integration',
    'deepseek_code.tools.git_conflict_tool',
    'cli.intel_runner',
    # --- dependencias externas ---
    'aiofiles', 'openai', 'aiohttp', 'websockets', 'pydantic', 'structlog', 'yaml', 'requests',
    'rich', 'rich.console', 'rich.markdown', 'rich.panel', 'rich.prompt', 'rich.box', 'rich.theme',
    'rich.table', 'rich.text',
]
tmp_ret = collect_all('rich')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('wasmtime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PyQt5')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PyQtWebEngine')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DeepSeekCode',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
