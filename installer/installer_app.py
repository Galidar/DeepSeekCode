"""Instalador GUI para DeepSeek-Code. Se compila con PyInstaller para generar DeepSeekCode_Setup.exe."""

import os
import sys
import shutil
import subprocess
import ctypes
import winreg
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

APP_NAME = "DeepSeek-Code"
APP_VERSION = "4.0.0"
APP_EXE = "DeepSeekCode.exe"
UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeek-Code"


def get_bundled_path():
    """Retorna la ruta base donde estan los archivos empaquetados."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'payload')
    return os.path.join(os.path.dirname(__file__), 'payload')


def is_admin():
    """Verifica si el proceso tiene permisos de administrador."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def needs_elevation(path):
    """Verifica si una ruta requiere permisos de administrador."""
    path_lower = path.lower()
    protected = [
        os.environ.get('PROGRAMFILES', r'C:\Program Files').lower(),
        os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)').lower(),
        os.environ.get('SYSTEMROOT', r'C:\Windows').lower(),
    ]
    return any(path_lower.startswith(p) for p in protected)


def request_elevation():
    """Re-lanza el instalador como administrador via UAC."""
    if getattr(sys, 'frozen', False):
        exe = sys.executable
    else:
        exe = sys.executable
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, " ".join(sys.argv[1:]), None, 1)


def get_default_install_dir():
    pf = os.environ.get('PROGRAMFILES', r'C:\Program Files')
    return os.path.join(pf, APP_NAME)


def create_shortcut(target, shortcut_path, description=""):
    """Crea un acceso directo .lnk usando PowerShell (no requiere pywin32)."""
    # Todos los argumentos son rutas controladas por el instalador, no input del usuario
    ps_script = (
        '$ws = New-Object -ComObject WScript.Shell; '
        f'$sc = $ws.CreateShortcut(\'{shortcut_path}\'); '
        f'$sc.TargetPath = \'{target}\'; '
        f'$sc.Description = \'{description}\'; '
        f'$sc.WorkingDirectory = \'{os.path.dirname(target)}\'; '
        '$sc.Save()'
    )
    subprocess.run(
        ['powershell', '-NoProfile', '-Command', ps_script],
        capture_output=True, timeout=10
    )


def install(install_dir, create_desktop, create_startmenu, progress_cb, status_cb, done_cb):
    """Ejecuta la instalacion en un thread separado."""
    try:
        payload = get_bundled_path()
        appdata = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), APP_NAME)

        # Paso 1: Crear directorios
        status_cb("Creando directorios...")
        progress_cb(10)
        os.makedirs(install_dir, exist_ok=True)
        os.makedirs(os.path.join(install_dir, 'skills'), exist_ok=True)
        os.makedirs(appdata, exist_ok=True)
        os.makedirs(os.path.join(appdata, 'skills'), exist_ok=True)

        # Paso 2: Copiar ejecutable
        status_cb("Copiando DeepSeekCode.exe...")
        progress_cb(20)
        src_exe = os.path.join(payload, APP_EXE)
        dst_exe = os.path.join(install_dir, APP_EXE)
        shutil.copy2(src_exe, dst_exe)

        # Paso 3: Copiar WASM a AppData (necesario para login web)
        status_cb("Copiando archivos de configuracion...")
        progress_cb(40)
        wasm_src = os.path.join(payload, 'sha3_wasm_bg.wasm')
        wasm_dst = os.path.join(appdata, 'sha3_wasm_bg.wasm')
        if os.path.exists(wasm_src) and not os.path.exists(wasm_dst):
            shutil.copy2(wasm_src, wasm_dst)

        # Paso 4: Copiar skills
        status_cb("Copiando skills...")
        progress_cb(60)
        skills_src = os.path.join(payload, 'skills')
        skills_dst = os.path.join(install_dir, 'skills')
        if os.path.exists(skills_src):
            for f in os.listdir(skills_src):
                src = os.path.join(skills_src, f)
                dst = os.path.join(skills_dst, f)
                if not os.path.exists(dst):  # No sobreescribir skills del usuario
                    shutil.copy2(src, dst)

        # Paso 4: Crear accesos directos
        progress_cb(75)
        if create_desktop:
            status_cb("Creando acceso directo en escritorio...")
            desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
            create_shortcut(dst_exe, os.path.join(desktop, f'{APP_NAME}.lnk'), APP_NAME)

        if create_startmenu:
            status_cb("Creando acceso directo en menu inicio...")
            start_menu = os.path.join(
                os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs'
            )
            menu_dir = os.path.join(start_menu, APP_NAME)
            os.makedirs(menu_dir, exist_ok=True)
            create_shortcut(dst_exe, os.path.join(menu_dir, f'{APP_NAME}.lnk'), APP_NAME)

        # Paso 5: Crear script de desinstalacion
        status_cb("Creando desinstalador...")
        progress_cb(85)
        _create_uninstaller(install_dir)

        # Paso 6: Registrar en Windows (Agregar/Quitar programas)
        status_cb("Registrando en Windows...")
        progress_cb(90)
        _register_uninstall(install_dir)

        progress_cb(100)
        status_cb("Instalacion completada!")
        done_cb(True, install_dir)

    except Exception as e:
        done_cb(False, str(e))


def _create_uninstaller(install_dir):
    """Crea un script .bat de desinstalacion."""
    uninstall_bat = os.path.join(install_dir, 'uninstall.bat')
    appdata_dir = os.path.join('%APPDATA%', APP_NAME)
    desktop_lnk = os.path.join(os.path.expanduser('~'), 'Desktop', f'{APP_NAME}.lnk')
    start_menu = os.path.join(
        '%APPDATA%', 'Microsoft', 'Windows', 'Start Menu', 'Programs', APP_NAME
    )

    bat_content = f'''@echo off
echo Desinstalando {APP_NAME}...
echo.
set /p confirm="Deseas eliminar tambien los datos de usuario en AppData? (s/n): "
if /i "%confirm%"=="s" (
    rmdir /s /q "{appdata_dir}" 2>nul
    echo Datos de usuario eliminados.
)
del "{desktop_lnk}" 2>nul
rmdir /s /q "{start_menu}" 2>nul
reg delete "HKLM\\{UNINSTALL_KEY}" /f 2>nul
reg delete "HKCU\\{UNINSTALL_KEY}" /f 2>nul
echo.
echo {APP_NAME} desinstalado.
echo La carpeta de instalacion se eliminara al cerrar esta ventana.
echo.
pause
cd /d "%TEMP%"
rmdir /s /q "{install_dir}" 2>nul
'''
    with open(uninstall_bat, 'w', encoding='utf-8') as f:
        f.write(bat_content)


def _register_uninstall(install_dir):
    """Registra la app en Agregar/Quitar programas de Windows (HKLM con admin)."""
    try:
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY)
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ,
                          os.path.join(install_dir, 'uninstall.bat'))
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
    except Exception:
        # Fallback a HKCU si no tenemos permisos HKLM
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ,
                              os.path.join(install_dir, 'uninstall.bat'))
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
            winreg.CloseKey(key)
        except Exception:
            pass


class InstallerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Instalador de {APP_NAME} v{APP_VERSION}")
        self.root.geometry("520x400")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a2e")

        self.install_dir = tk.StringVar(value=get_default_install_dir())
        self.create_desktop = tk.BooleanVar(value=True)
        self.create_startmenu = tk.BooleanVar(value=True)

        self._build_ui()
        self.root.mainloop()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#1a1a2e')
        style.configure('TLabel', background='#1a1a2e', foreground='#e0e0e0',
                         font=('Segoe UI', 10))
        style.configure('Title.TLabel', background='#1a1a2e', foreground='#00d2ff',
                         font=('Segoe UI', 16, 'bold'))
        style.configure('TButton', font=('Segoe UI', 10))
        style.configure('TCheckbutton', background='#1a1a2e', foreground='#e0e0e0',
                         font=('Segoe UI', 10))

        main = ttk.Frame(self.root, padding=20)
        main.pack(fill='both', expand=True)

        # Titulo
        ttk.Label(main, text="DeepSeek-Code", style='Title.TLabel').pack(pady=(0, 5))
        ttk.Label(main, text=f"Version {APP_VERSION} — Asistente con herramientas avanzadas").pack()
        ttk.Separator(main, orient='horizontal').pack(fill='x', pady=15)

        # Directorio de instalacion
        dir_frame = ttk.Frame(main)
        dir_frame.pack(fill='x', pady=5)
        ttk.Label(dir_frame, text="Directorio de instalacion:").pack(anchor='w')

        path_frame = ttk.Frame(dir_frame)
        path_frame.pack(fill='x', pady=3)
        self.dir_entry = ttk.Entry(path_frame, textvariable=self.install_dir, width=50)
        self.dir_entry.pack(side='left', fill='x', expand=True)
        ttk.Button(path_frame, text="...", width=3, command=self._browse).pack(
            side='right', padx=(5, 0))

        # Opciones
        opts_frame = ttk.Frame(main)
        opts_frame.pack(fill='x', pady=10)
        ttk.Checkbutton(opts_frame, text="Crear acceso directo en el escritorio",
                         variable=self.create_desktop).pack(anchor='w')
        ttk.Checkbutton(opts_frame, text="Crear acceso directo en menu inicio",
                         variable=self.create_startmenu).pack(anchor='w')

        # Barra de progreso
        self.progress = ttk.Progressbar(main, mode='determinate', length=460)
        self.progress.pack(fill='x', pady=10)

        # Status
        self.status_label = ttk.Label(main, text="Listo para instalar")
        self.status_label.pack()

        # Botones
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill='x', pady=(15, 0))
        self.install_btn = ttk.Button(btn_frame, text="Instalar", command=self._start_install)
        self.install_btn.pack(side='right')
        ttk.Button(btn_frame, text="Cancelar", command=self.root.quit).pack(side='right', padx=5)

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.install_dir.get())
        if d:
            self.install_dir.set(d)

    def _start_install(self):
        self.install_btn.configure(state='disabled')
        self.dir_entry.configure(state='disabled')

        threading.Thread(
            target=install,
            args=(
                self.install_dir.get(),
                self.create_desktop.get(),
                self.create_startmenu.get(),
                self._update_progress,
                self._update_status,
                self._on_done,
            ),
            daemon=True,
        ).start()

    def _update_progress(self, value):
        self.root.after(0, lambda: self.progress.configure(value=value))

    def _update_status(self, text):
        self.root.after(0, lambda: self.status_label.configure(text=text))

    def _on_done(self, success, detail):
        def _show():
            if success:
                msg = f"{APP_NAME} se instalo correctamente en:\n{detail}"
                if messagebox.askyesno("Instalacion completada",
                                        f"{msg}\n\nDeseas ejecutar {APP_NAME} ahora?"):
                    os.startfile(os.path.join(detail, APP_EXE))
                self.root.quit()
            else:
                messagebox.showerror("Error", f"Error durante la instalacion:\n{detail}")
                self.install_btn.configure(state='normal')
                self.dir_entry.configure(state='normal')
        self.root.after(0, _show)


if __name__ == '__main__':
    # Solicitar admin automaticamente al iniciar
    if not is_admin():
        request_elevation()
        sys.exit(0)
    InstallerGUI()
