# WireGuard — nodo Linux (generado por provisioning Nest)
[Interface]
Address = {{VPN_IP}}/32
PrivateKey = {{NODE_PRIVATE_KEY}}

[Peer]
PublicKey = {{HUB_PUBLIC_KEY}}
Endpoint = {{HUB_ENDPOINT}}
AllowedIPs = 10.66.0.1/32
PersistentKeepalive = 25
