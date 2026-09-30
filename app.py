#!/usr/bin/env python3
from __future__ import annotations
import getpass
import logging
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

# ---------- Util ----------
def run(cmd: List[str], *, check: bool = True, env: dict | None = None) -> None:
    logging.debug("RUN: %s", " ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=check, env=env)

def run_shell(cmd: str, *, check: bool = True, env: dict | None = None) -> None:
    logging.debug("SHELL: %s", cmd)
    subprocess.run(cmd, shell=True, check=check, env=env)

def ensure_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("Script ini harus dijalankan sebagai root (sudo).")

# ---------- Konfigurasi ----------
@dataclass
class SetupConfig:
    crd_auth_command: str  # perintah CRD dari web (tanpa --pin)
    username: str
    password: str
    pin: str  # minimal 6 digit

# ---------- Installer ----------
class CRDInstaller:
    def __init__(self, cfg: SetupConfig):
        self.cfg = cfg
        self.env_noninteractive = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}

    def apt_update(self):
        run(["apt-get", "update", "-y"], env=self.env_noninteractive)

    def install_desktop(self):
        pkgs = ["xfce4", "desktop-base", "xfce4-terminal", "xscreensaver", "dbus-x11"]
        run(["apt-get", "install", "-y", *pkgs], env=self.env_noninteractive)
        Path("/etc/chrome-remote-desktop-session").write_text(
            'exec /etc/X11/Xsession /usr/bin/xfce4-session\n',
            encoding="utf-8"
        )
        run(["service", "dbus", "start"])

    def ensure_user(self):
        try:
            run(["id", self.cfg.username])
            exists = True
        except subprocess.CalledProcessError:
            exists = False

        if not exists:
            run(["useradd", "-m", "-s", "/bin/bash", self.cfg.username])
            logging.info("User %s dibuat.", self.cfg.username)

        run(["usermod", "-aG", "sudo", self.cfg.username])
        run_shell(f"echo {shlex.quote(self.cfg.username)}:{shlex.quote(self.cfg.password)} | chpasswd")

    def ensure_group(self, group: str) -> None:
        try:
            run(["getent", "group", group])
        except subprocess.CalledProcessError:
            run(["groupadd", group])
            logging.info("Group %s dibuat.", group)

    def install_crd(self):
        deb = Path("chrome-remote-desktop_current_amd64.deb")
        run(["wget", "-q", "https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb"])
        try:
            run(["dpkg", "--install", str(deb)])
        except subprocess.CalledProcessError:
            run(["apt-get", "install", "-f", "-y"], env=self.env_noninteractive)
        finally:
            if deb.exists():
                deb.unlink()

    def start_system_service(self, service: str) -> None:
        if shutil.which("systemctl") is not None:
            try:
                run(["systemctl", "daemon-reload"])
                run(["systemctl", "start", service])
                return
            except subprocess.CalledProcessError:
                logging.warning(
                    "systemctl gagal memulai %s; mencoba fallback ke service.", service
                )

        run(["service", service, "start"])

    def start_crd(self):
        self.ensure_group("chrome-remote-desktop")
        run(["usermod", "-aG", "chrome-remote-desktop", self.cfg.username])
        command = f"{self.cfg.crd_auth_command} --pin={shlex.quote(self.cfg.pin)}"
        run(["su", "-", self.cfg.username, "-c", command])
        self.start_system_service("chrome-remote-desktop")

    def run_all(self):
        ensure_root()
        if len(self.cfg.pin) < 6 or not self.cfg.pin.isdigit():
            raise SystemExit("PIN harus numerik dan minimal 6 digit.")
        if not self.cfg.crd_auth_command.strip():
            raise SystemExit("Kode/Perintah otorisasi CRD tidak boleh kosong.")

        logging.info("Memperbarui paket...")
        self.apt_update()

        logging.info("Menginstall Chrome Remote Desktop...")
        self.install_crd()

        logging.info("Menginstall XFCE4 Desktop Environment...")
        self.install_desktop()

        logging.info("Membuat & mengatur user...")
        self.ensure_user()

        logging.info("Menjalankan Chrome Remote Desktop...")
        self.start_crd()

        logging.info("Setup selesai. Anda dapat mengakses CRD dengan PIN yang sudah dibuat.")

# ---------- Entry Point ----------
def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("== Setup Chrome Remote Desktop (CRD) + XFCE ==")
    crd_auth_command = input("Tempel perintah otorisasi CRD (tanpa --pin di akhir): ").strip()

    username = input("Username baru (default: user): ").strip() or "user"
    password = getpass.getpass(f"Password untuk {username}: ").strip() or "root"
    pin = getpass.getpass("PIN CRD (min 6 digit): ").strip() or "123456"

    cfg = SetupConfig(
        crd_auth_command=crd_auth_command,
        username=username,
        password=password,
        pin=pin
    )

    try:
        installer = CRDInstaller(cfg)
        installer.run_all()
    except subprocess.CalledProcessError as e:
        logging.error("Perintah gagal: %s", e)
        raise SystemExit(1)
    except Exception as e:
        logging.error("Gagal: %s", e)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
