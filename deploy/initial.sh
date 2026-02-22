#!/bin/bash
set -e -o pipefail

PROJECT_DIR=${HOME}/projects/mainframe

# For new rpi https://www.thedigitalpictureframe.com/stay-connected-enhancing-raspberry-pi-wi-fi-stability-by-turning-off-power-management/

if [ "$1" == "--continue" ]; then

  cat "${PROJECT_DIR}/deploy/ngrok.yml" >> "$HOME/.config/ngrok/ngrok.yml"
  echo "WARNING: If you have a custom domain - fill it in the ~/.config/ngrok.yml"

  REDIS_DIR=/etc/redis
  echo "[redis] Installing redis server"
  sudo apt install -y redis-server
  echo "[redis] Setting supervised from no to systemd"
  sudo sed -i -e 's/supervised no/supervised systemd/g' "${REDIS_DIR}/redis.conf"
  sudo systemctl restart redis.service
  echo "[redis] Done."

  echo "=== Initial setup Done! ==="
  echo "[datadog] please create an api key and follow the instructions here https://app.datadoghq.eu/account/settings/agent/latest?platform=debian"
  echo "[env] Please fill out the env vars inside mainframe/backend/.env"
  echo "then do '~/projects/mainframe/deploy/setup.sh requirements restart'"
  exit 0
fi

echo "[Power save] Turning power_save off to keep wifi from disconnecting" && sudo iw dev wlan0 set power_save off
echo "[Power managerment] Turning iwconfig power management off to keep wifi from disconnecting" && sudo iwconfig wlan0 power off

echo "[homeassistant] Docker setup"
echo "[homeassistant][docker] Add Docker's official GPG key:"
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "[homeassistant][docker] Add the repository to Apt sources:"
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
echo "[homeassistant][docker] Installing latest Docker"
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
echo "[homeassistant][docker] Done."
echo "[homeassistant] running docker" && \
  sudo docker run -d \
    --name homeassistant \
    --privileged \
    --restart=unless-stopped \
    -e TZ=MY_TIME_ZONE \
    -v /PATH_TO_YOUR_CONFIG:/config \
    -v /run/dbus:/run/dbus:ro \
    --network=host \
    ghcr.io/home-assistant/home-assistant:stable

if [ -d "${HOME}/.oh-my-zsh" ]; then
  echo "[zsh] ${HOME}/.oh-my-zsh - path already exists - skipping installation"
else
  echo "[zsh] Installing zsh" && sudo apt-get install -y zsh
  echo "[zsh] Installing ohmyzsh" && sh -c "$(curl --proto "=https" -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
  echo "[zsh] Setting .zshrc aliases" && cat "${PROJECT_DIR}/deploy/.zshrc" >> "${HOME}/.zshrc"
  echo "[zsh] Setting theme to af-magic" && sed -i -e 's/ZSH_THEME="robbyrussell"/ZSH_THEME="af-magic"/g' "${HOME}/.zshrc"
  echo "[zsh] Setting .bashrc - zsh " && cat "zsh" >> "${HOME}/.bashrc"
  echo "[zsh] Done."
fi

echo "[env] Setting .env placeholder" &&
ENV_FILE="${PROJECT_DIR}/src/mainframe/.env"
if [ -f "$ENV_FILE" ]; then
  echo "env file already exists";
else
  cat "${PROJECT_DIR}/deploy/.env" >> "$ENV_FILE";
fi

LOGS_DIR=/var/log/mainframe
echo "$(date -u +"%Y-%m-%d %H:%M:%SZ") - [logs] Creating logs path"
if [ -d "${LOGS_DIR}" ]; then
  echo "$(date -u +"%Y-%m-%d %H:%M:%SZ") - [logs] Path already exists";
else
  sudo mkdir -p "${LOGS_DIR}";
  sudo chown -R rpi:rpi ${LOGS_DIR}
  echo "$(date -u +"%Y-%m-%d %H:%M:%SZ") - [logs] Path created"
fi

VIRTUALENV_DIR=${HOME}/projects/.virtualenvs/mainframe
echo "$(date -u +"%Y-%m-%d %H:%M:%SZ") - [venv] Creating venv"
if [ -d "${VIRTUALENV_DIR}" ]; then
  echo "$(date -u +"%Y-%m-%d %H:%M:%SZ") - [venv] Already exists"
else
  python -m venv "${VIRTUALENV_DIR}";
  echo "$(date -u +"%Y-%m-%d %H:%M:%SZ") - [venv] Created"
fi
echo "[env] Done."

echo "[postgres] Installing postgres deps..." && sudo apt-get -y install libpq-dev && echo "[postgres] Done."

#echo "[sklearn] Installing scikit-learn deps..." && \
#sudo apt-get install gfortran libatlas-base-dev libopenblas-dev liblapack-dev -y && \
#echo "[sklearn] Done."

echo "[redis] Installing redis..." && \
  sudo apt install redis-server -y && \
  sudo systemctl enable redis && \
  sudo systemctl start redis && \
  echo "[redis] Done."

NGINX_DIR=/etc/nginx
NGINX_AVAILABLE="${NGINX_DIR}/sites-available/mainframe"
NGINX_ENABLED="${NGINX_DIR}/sites-enabled/mainframe"
NGINX_ENABLED_DEFAULT="${NGINX_DIR}/sites-enabled/default"
PROJECT_DIR=${HOME}/projects/mainframe
echo "[nginx] Installing nginx" && sudo apt-get -y install nginx
echo "[nginx] Adding configuration"
if [ -f "$NGINX_AVAILABLE" ]; then sudo rm $NGINX_AVAILABLE && echo "Deleted ${NGINX_AVAILABLE}"; else echo "File not found: ${NGINX_AVAILABLE}"; fi
if [ -f "$NGINX_ENABLED" ]; then sudo rm $NGINX_ENABLED && echo "Deleted ${NGINX_ENABLED}"; else echo "File not found: ${NGINX_ENABLED}"; fi
if [ -f "$NGINX_ENABLED_DEFAULT" ]; then sudo rm $NGINX_ENABLED_DEFAULT && echo "Deleted ${NGINX_ENABLED_DEFAULT}"; else echo "File not found: ${NGINX_ENABLED_DEFAULT}"; fi
sudo touch ${NGINX_AVAILABLE}
sudo chown rpi $NGINX_AVAILABLE
cat "${PROJECT_DIR}/deploy/nginx.conf" >> $NGINX_AVAILABLE
sudo ln -s ${NGINX_AVAILABLE} $NGINX_DIR/sites-enabled
sudo nginx -t
sudo systemctl restart nginx
echo "[nginx] Done."

echo "[ngrok] Installing ngrok"
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null && echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list && sudo apt update && sudo apt install ngrok

echo "[ngrok] Done."
echo "[ngrok] Log into your ngrok account https://dashboard.ngrok.com/get-started/your-authtoken"
echo "and copy add your auth token here by doing:"
echo "ngrok config add-authtoken <your auth token here>"
echo "then continue with ./deploy/initial.sh --continue"
exit 0
