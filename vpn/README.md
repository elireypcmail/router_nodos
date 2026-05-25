# VPN en el nodo (tienda)

## Linux

1. Instalar WireGuard: `sudo apt install wireguard`
2. Guardar el `.conf` entregado por provisioning en `/etc/wireguard/wg0.conf`
3. `sudo wg-quick up wg0`
4. Copiar `.env` del bundle y arrancar API: `python main.py`

## Windows

1. Instalar [WireGuard for Windows](https://www.wireguard.com/install/)
2. Importar túnel desde el archivo `.conf` del bundle
3. Activar el túnel
4. Configurar `.env` y ejecutar `python main.py` (o servicio NSSM)

## Firewall

Permitir tráfico entrante al puerto de la API (8443) **solo** desde `10.66.0.1` (hub).
