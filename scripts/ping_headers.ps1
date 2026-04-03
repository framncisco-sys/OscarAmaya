# Muestra las cabeceras de /ping/ (Invoke-WebRequest falla en 404 y no rellena $r bien).
# Debes ver X-PBR-URLconf-Routes: 8. Si no aparece, el puerto lo atiende otro proceso (.\who_owns_port.ps1).
param([int]$Port = 8000)
$u = "http://127.0.0.1:$Port/ping/"
curl.exe -s -D - -o NUL $u
