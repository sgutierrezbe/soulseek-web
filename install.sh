#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  soulseek-web — instalador automático
#  Uso: sudo bash install.sh
#  One-liner: curl -sSL https://raw.githubusercontent.com/sgutierrezbe/soulseek-web/main/install.sh | sudo bash
# ──────────────────────────────────────────────────────────────────────────────
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="/opt/soulseek-web"
SERVICE_NAME="soulseek-web"
PORT=8080
REPO="https://github.com/sgutierrezbe/soulseek-web.git"

header() {
  echo ""
  echo -e "${GREEN}${BOLD}"
  echo "  ███████╗██╗     ███████╗██╗  ██╗   ██╗    ██╗███████╗██████╗ "
  echo "  ██╔════╝██║     ██╔════╝██║ ██╔╝   ██║    ██║██╔════╝██╔══██╗"
  echo "  ███████╗██║     ███████╗█████╔╝    ██║ █╗ ██║█████╗  ██████╔╝"
  echo "  ╚════██║██║     ╚════██║██╔═██╗    ██║███╗██║██╔══╝  ██╔══██╗"
  echo "  ███████║███████╗███████║██║  ██╗   ╚███╔███╔╝███████╗██████╔╝"
  echo "  ╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝    ╚══╝╚══╝ ╚══════╝╚═════╝ "
  echo -e "${NC}"
  echo "  Web UI para Soulseek — instalador automático"
  echo ""
}

step()  { echo -e "${BOLD}→ $1${NC}"; }
ok()    { echo -e "${GREEN}  ✓ $1${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠ $1${NC}"; }
die()   { echo -e "${RED}  ✗ $1${NC}"; exit 1; }

# ── Verificaciones previas ────────────────────────────────────────────────────

header

[[ $EUID -eq 0 ]] || die "Corré este script como root:  sudo bash install.sh"

step "Verificando dependencias del sistema..."

# Python 3.11+
if command -v python3 &>/dev/null; then
  PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  PY_MAJ=$(python3 -c "import sys; print(sys.version_info.major)")
  PY_MIN=$(python3 -c "import sys; print(sys.version_info.minor)")
  if [[ $PY_MAJ -lt 3 ]] || [[ $PY_MAJ -eq 3 && $PY_MIN -lt 11 ]]; then
    die "Se requiere Python 3.11+. Versión encontrada: $PY_VER"
  fi
  ok "Python $PY_VER"
else
  die "Python 3 no encontrado. Instalalo con:  apt install python3"
fi

# git
if ! command -v git &>/dev/null; then
  step "Instalando git..."
  apt-get install -y git -qq 2>/dev/null || die "No se pudo instalar git"
fi
ok "git"

# python3-venv
if ! python3 -m venv --without-pip /tmp/test_venv &>/dev/null 2>&1; then
  step "Instalando python3-venv..."
  apt-get install -y python3-venv -qq 2>/dev/null || die "No se pudo instalar python3-venv"
fi
rm -rf /tmp/test_venv
ok "python3-venv"

# ── Clonar o actualizar ───────────────────────────────────────────────────────

echo ""
if [[ -d "$INSTALL_DIR/.git" ]]; then
  step "Actualizando instalación existente en $INSTALL_DIR ..."
  cd "$INSTALL_DIR"
  git pull --quiet
  ok "Repositorio actualizado"
else
  step "Clonando repositorio en $INSTALL_DIR ..."
  git clone --quiet "$REPO" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
  ok "Repositorio clonado"
fi

# ── Entorno virtual y dependencias ───────────────────────────────────────────

echo ""
step "Instalando dependencias Python..."
python3 -m venv venv
venv/bin/pip install --quiet --upgrade pip
venv/bin/pip install --quiet -r requirements.txt
ok "Dependencias instaladas"

# ── Permisos ──────────────────────────────────────────────────────────────────

chmod +x "$INSTALL_DIR/install.sh" 2>/dev/null || true

# ── Servicio systemd ──────────────────────────────────────────────────────────

echo ""
step "Configurando servicio systemd..."

cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Soulseek Web UI
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn main:app --host 0.0.0.0 --port ${PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --quiet "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

sleep 2

# ── Resultado ─────────────────────────────────────────────────────────────────

echo ""
if systemctl is-active --quiet "${SERVICE_NAME}"; then
  LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo -e "${GREEN}${BOLD}  ✓ soulseek-web instalado y corriendo!${NC}"
  echo ""
  echo "  Accedé desde el navegador:"
  echo -e "  ${YELLOW}${BOLD}  ➜  http://${LAN_IP}:${PORT}${NC}"
  echo ""
  echo "  La primera vez que abras la UI te pedirá las credenciales de slskd."
  echo ""
  echo "  Comandos útiles:"
  echo "    sudo systemctl status ${SERVICE_NAME}"
  echo "    sudo systemctl restart ${SERVICE_NAME}"
  echo "    sudo journalctl -u ${SERVICE_NAME} -f"
  echo ""
else
  echo -e "${RED}El servicio no pudo iniciarse. Revisá los logs:${NC}"
  journalctl -u "${SERVICE_NAME}" -n 30 --no-pager
  exit 1
fi
