<# 
.SYNOPSIS
    Demo automatizada del sistema de Matching Inteligente (CASO 2)
.DESCRIPTION
    Ejecuta paso a paso la demostraciÃ³n completa:
    1. Bandeja simulada hora por hora (RF-15)
    2. ClasificaciÃ³n de correos (RF-16)
    3. Matching por vacante con relajaciones (RF-07, RNF-04)
    4. Consultas al reclutador (RF-04)
    5. Reportes por vacante (RF-11)
    6. Procesamiento de cola mÃºltiples vacantes (RF-13)
.NOTES
    Requiere: Python 3.10+, dependencias instaladas (pip install -r requirements.txt)
    Ejecutar desde la raÃ­z del proyecto: .\demo.ps1
#>

param(
    [switch]$Rapido = $false,        # Saltar pausas largas
    [switch]$SoloBandeja = $false,   # Solo la simulaciÃ³n de bandeja
    [int]$HorasDemo = 8              # Horas simuladas a mostrar (mÃ¡x 24)
)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# ConfiguraciÃ³n de colores y helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
$ROJO      = [ConsoleColor]::Red
$VERDE     = [ConsoleColor]::Green
$AMARILLO  = [ConsoleColor]::Yellow
$CIAN      = [ConsoleColor]::Cyan
$MAGENTA   = [ConsoleColor]::Magenta
$GRIS      = [ConsoleColor]::DarkGray
$BLANCO    = [ConsoleColor]::White

function Escribir-Titulo  { param($t) Write-Host "`n$(('='*70))" -Fore $CIAN; Write-Host "  $t" -Fore $CIAN; Write-Host "$(('='*70))`n" -Fore $CIAN }
function Escribir-Paso    { param($n,$t) Write-Host "`nâ–¶ PASO $n: $t" -Fore $VERDE }
function Escribir-Info    { param($t) Write-Host "  â„¹ $t" -Fore $AMARILLO }
function Escribir-Exito   { param($t) Write-Host "  âœ… $t" -Fore $VERDE }
function Escribir-Advert  { param($t) Write-Host "  âš  $t" -Fore $MAGENTA }
function Escribir-Error   { param($t) Write-Host "  âŒ $t" -Fore $ROJO }
function Pausa            { param([int]$s=3) if (-not $Rapido) { Start-Sleep -Seconds $s } }
function PausaTecla       { if (-not $Rapido) { Write-Host "`n  [Presione ENTER para continuar...]" -Fore $GRIS -NoNewline; Read-Host | Out-Null } }

# Verificar que estamos en el directorio correcto
if (-not (Test-Path "src\bandeja_simulada.py")) {
    Escribir-Error "Ejecute este script desde la raÃ­z del proyecto (donde estÃ¡ src/)"
    exit 1
}

Escribir-Titulo "ðŸŽ¯ DEMO AUTOMATIZADA - MATCHING INTELIGENTE CASO 2"
Write-Host "  Requisitos cubiertos: RF-07, RF-11, RF-13, RF-15, RF-16, RNF-04, RNF-02, RNF-09" -Fore $GRIS
Write-Host "  Modo: $([string]::Format('{0}', (if ($Rapido) 'RÃPIDO' else 'NORMAL')))" -Fore $GRIS
PausaTecla

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 1: Ver la bandeja simulada (fuente de verdad)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Escribir-Paso 1 "BANDEJA SIMULADA - Fuente de datos (RF-15)"
Escribir-Info "Archivo: data/bandeja.json â€” 12 correos repartidos en ~19 horas simuladas"
Escribir-Info "Contiene: 4 vacantes con vacante_estructurada (V001-V004), 1 reenvÃ­o (b4), 1 gestiÃ³n (b0), 2 candidatos (b6,b10), 4 basura (b7-b9), 1 incompleta (b5)"

python -c "
import json
with open('data/bandeja.json', 'r', encoding='utf-8-sig') as f:
    b = json.load(f)
print(f'Inicio simulado: {b[\"inicio\"]}')
print(f'Total correos: {len(b[\"correos\"])}')
for c in b['correos']:
    ve = c.get('vacante_estructurada')
    tag = f' â†’ VACANTE {ve[\"id\"]} ({ve[\"scenario\"]})' if ve else ''
    reenvio = f' (reenvÃ­o de {c[\"reenvio_de\"]})' if c.get('reenvio_de') else ''
    nota = c.get('nota', '')
    print(f'  {c[\"message_id\"]:3s} @ {c[\"timestamp\"][11:16]} | {c[\"asunto\"][:55]:55s} {tag}{reenvio} {nota}')
"
PausaTecla

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 2: Ejecutar bandeja simulada hora por hora
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Escribir-Paso 2 "SIMULACIÃ“N HORA A HORA - RF-15 + RF-16 + RF-13"
Escribir-Info "Cada ciclo = 1 hora simulada. Solo correos de VACANTE disparan matching."
Escribir-Info "ReenvÃ­os â†’ duplicados (no disparan). GestiÃ³n/candidatos/basura â†’ no_relacionado."
Escribir-Info "Vacante sin skills (b5) â†’ revisiÃ³n_humana (no se inventan criterios)."
Escribir-Info "Cola procesa vacantes en orden de llegada (RF-13). LÃ­mite 24h (RNF-04)."

$cmd = "python -m src.bandeja_simulada --reiniciar --horas $HorasDemo"
if ($Rapido) { $cmd += " --ritmo-real 0" } else { $cmd += " --ritmo-real 0.5" }
Escribir-Info "Comando: $cmd"
Write-Host ""
& $cmd
PausaTecla

if ($SoloBandeja) {
    Escribir-Titulo "âœ… DEMO BANDEJA COMPLETADA (modo --SoloBandeja)"
    exit 0
}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 3: Ver reportes generados
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Escribir-Paso 3 "REPORTES POR VACANTE - RF-11"
Escribir-Info "Cada vacante genera: reporte_<id>.md (ejecutivo), reporte_<id>.json (completo), auditoria_<id>.csv, shortlist_<id>.csv"

$reportes = Get-ChildItem reports/reporte_V*.md | Sort-Object Name
foreach ($r in $reportes) {
    $vid = $r.BaseName -replace 'reporte_', ''
    Escribir-Exito "Reporte $vid generado ($([math]::Round($r.Length/1024,1)) KB)"
}

# Mostrar resumen ejecutivo del primero
$primerReporte = $reportes[0]
Escribir-Info "Vista previa del reporte $($primerReporte.BaseName -replace 'reporte_', ''):"
Get-Content $primerReporte.FullName | Select-Object -First 40 | ForEach-Object { Write-Host "  $_" -Fore $GRIS }
Write-Host "  ..." -Fore $GRIS
PausaTecla

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 4: Matching manual de una vacante (detalle tÃ©cnico)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Escribir-Paso 4 "MATCHING MANUAL - Vacante V001 (fÃ¡cil) - RF-07 + RNF-04"
Escribir-Info "Ejecuta el grafo LangGraph con lÃ­mites: mÃ¡x 3 relajaciones, 3 consultas reclutador, 400 pasos, 30 llamadas LLM"
Escribir-Info "Modo: without_llm (determinÃ­stico, puntaje en cÃ³digo, LLM solo para redacciÃ³n)"

python -m src.ejecutar_matching V001 --salida data/salida_demo_V001.json
PausaTecla

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 5: Ver auditorÃ­a (RF-10)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Escribir-Paso 5 "AUDITORÃA PASO A PASO - RF-10 (4 columnas: iteraciÃ³n, nodo, decisiÃ³n, motivo)"
Escribir-Info "Archivo: reports/auditoria_V001.csv"
Write-Host ""
Import-Csv reports/auditoria_V001.csv | Select-Object -First 15 | Format-Table -AutoSize | Out-Host
Write-Host "  ... ($(Import-Csv reports/auditoria_V001.csv).Count eventos totales)" -Fore $GRIS
PausaTecla

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 6: Consultas al reclutador (RF-04)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Escribir-Paso 6 "CONSULTAS AL RECLUTADOR - RF-04 (mÃ¡x 3 por corrida)"
Escribir-Info "Si el candidato no trae availability_date, se pregunta al reclutador simulado (data/reclutador.json)"
Escribir-Info "Respuesta 'no se sabe' o sin respuesta â†’ campo vacÃ­o â†’ 0 puntos en disponibilidad (no se inventa)"

# Extraer tabla de consultas del reporte
$reporteV001 = Get-Content reports/reporte_V001.md -Raw
if ($reporteV001 -match '(?s)## Consultas al reclutador.*?\|(.*?)\n##') {
    $tabla = $matches[1].Trim()
    $lineas = $tabla -split '\n' | Where-Object { $_ -match '\|' }
    foreach ($l in $lineas[0..([math]::Min(10, $lineas.Count-1))]) {
        Write-Host "  $l" -Fore $GRIS
    }
}
PausaTecla

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 7: Relajaciones aplicadas (RF-06/RF-07)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Escribir-Paso 7 "RELAJACIONES AUTOMÃTICAS - RF-06/RF-07 (mÃ¡x 3, skills obligatorios NUNCA)"
Escribir-Info "Orden: 1) Fecha +2 sem, 2) Experiencia -1 aÃ±o, 3) InglÃ©s -1 nivel"
Escribir-Info "Se detienen al conseguir 3 candidatos que superen umbral (70 pts) y cubran los 3 puestos"

$reporteV001 = Get-Content reports/reporte_V001.md -Raw
if ($reporteV001 -match '(?s)## Criterios relajados.*?\|(.*?)\n##') {
    $tabla = $matches[1].Trim()
    $lineas = $tabla -split '\n' | Where-Object { $_ -match '\|' }
    foreach ($l in $lineas) { Write-Host "  $l" -Fore $GRIS }
}
PausaTecla

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 8: ClasificaciÃ³n de correos reales (AgentMail) - opcional
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if (Test-Path ".env") {
    $envContent = Get-Content .env -Raw
    if ($envContent -match 'AGENTMAIL_API_KEY') {
        Escribir-Paso 8 "CLASIFICACIÃ“N CORREOS REALES - AgentMail (RNF-09)"
        Escribir-Info "Lee la bandeja real y clasifica sin procesar (modo verificaciÃ³n)"
        Write-Host ""
        python -m src.verificar_correos
        PausaTecla
    }
    else {
        Escribir-Advert "PASO 8 omitido: AGENTMAIL_API_KEY no configurado en .env"
        Pausa 1
    }
}
else {
    Escribir-Advert "PASO 8 omitido: archivo .env no encontrado"
    Pausa 1
}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 9: Verificar candidatos entrantes
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Escribir-Paso 9 "VERIFICACIÃ“N CANDIDATOS - Correos que describen perfiles"
Escribir-Info "Los correos clasificados como 'candidato' se guardan en data/candidatos.csv para futuros matchings"
python -m src.verificar_correos 2>$null; if ($LASTEXITCODE -ne 0) { Escribir-Advert "Requiere bandeja AgentMail configurada" } "Requiere bandeja AgentMail configurada"
PausaTecla

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 10: Resumen de archivos generados
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Escribir-Paso 10 "RESUMEN DE ARTEFACTOS GENERADOS"
Write-Host ""
Write-Host "  ðŸ“ data/" -Fore $CIAN
Write-Host "    â”œâ”€â”€ bandeja.json              # Bandeja simulada (fuente)"
Write-Host "    â”œâ”€â”€ bandeja_procesados.json   # IDs ya procesados (persistencia)"
Write-Host "    â”œâ”€â”€ cola_vacantes.json        # Cola de vacantes de la corrida"
Write-Host "    â”œâ”€â”€ vacantes.json             # CatÃ¡logo maestro"
Write-Host "    â”œâ”€â”€ candidatos.csv            # 41 perfiles base + nuevos de correos"
Write-Host "    â””â”€â”€ reclutador.json           # Respuestas simuladas disponibilidad"
Write-Host ""
Write-Host "  ðŸ“ reports/" -Fore $CIAN
$archivos = Get-ChildItem reports/ -File | Sort-Object Name
foreach ($a in $archivos) {
    $kb = [math]::Round($a.Length/1024, 1)
    Write-Host "    â”œâ”€â”€ $($a.Name) ($kb KB)" -Fore $GRIS
}
Write-Host ""
Write-Host "  ðŸ“ logs/" -Fore $CIAN
Get-ChildItem logs/ -File | ForEach-Object { Write-Host "    â”œâ”€â”€ $($_.Name) ($([math]::Round($_.Length/1024,1)) KB)" -Fore $GRIS }

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# CIERRE
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Escribir-Titulo "âœ… DEMO COMPLETADA"
Write-Host "  Todos los requisitos demostrados:" -Fore $VERDE
Write-Host "  â€¢ RF-15: Bandeja simulada hora a hora (ciclos 1h, max 24h)"
Write-Host "  â€¢ RF-16: ClasificaciÃ³n 4 clases + cola de vacantes"
Write-Host "  â€¢ RF-13: Cola procesa mÃºltiples vacantes en orden (V001â†’V002â†’V003â†’V004)"
Write-Host "  â€¢ RF-11: Reporte .md + .json + CSV por vacante"
Write-Host "  â€¢ RF-10: AuditorÃ­a 4 columnas (iteraciÃ³n, nodo, decisiÃ³n, motivo)"
Write-Host "  â€¢ RF-07 + RNF-04: Parada 3 relajaciones, lÃ­mites grafo (400 pasos)"
Write-Host "  â€¢ RF-04: Consultas reclutador (mÃ¡x 3, 'no se sabe' = 0 pts)"
Write-Host "  â€¢ RNF-02: Modo without_llm determinÃ­stico"
Write-Host "  â€¢ RNF-09: Sin credenciales en cÃ³digo (.env para AgentMail)"
Write-Host ""
Write-Host "  Para demo con AgentMail real:" -Fore $AMARILLO
Write-Host "    1. Configure AGENTMAIL_API_KEY y AGENTMAIL_INBOX_ID en .env"
Write-Host "    2. Ejecute: python -m src.leer_correos --vigilar"
Write-Host ""
PausaTecla
