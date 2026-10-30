#!/usr/bin/env bash
# #############################################################################
# Demo automatizada del sistema de Matching Inteligente (CASO 2)
# #############################################################################
# Ejecuta paso a paso la demostración completa:
#   1. Bandeja simulada hora por hora (RF-15)
#   2. Clasificación de correos (RF-16)
#   3. Matching por vacante con relajaciones (RF-07, RNF-04)
#   4. Consultas al reclutador (RF-04)
#   5. Reportes por vacante (RF-11)
#   6. Procesamiento de cola múltiples vacantes (RF-13)
# #############################################################################
# Uso: ./demo.sh [--rapido] [--solo-bandeja] [--horas N]
# #############################################################################

set -euo pipefail

RAPIDO=false
SOLO_BANDEJA=false
HORAS_DEMO=8

while [[ $# -gt 0 ]]; do
    case $1 in
        --rapido) RAPIDO=true ;;
        --solo-bandeja) SOLO_BANDEJA=true ;;
        --horas) HORAS_DEMO="$2"; shift ;;
        *) echo "Opción desconocida: $1"; exit 1 ;;
    esac
    shift
done

# Colores
ROJO='\033[0;31m'
VERDE='\033[0;32m'
AMARILLO='\033[1;33m'
CIAN='\033[0;36m'
MAGENTA='\033[0;35m'
GRIS='\033[0;90m'
NC='\033[0m' # Sin color

escribir_titulo() { echo -e "\n${CIAN}======================================================================${NC}"; echo -e "  $1"; echo -e "======================================================================${NC}\n"; }
escribir_paso()   { echo -e "\n${VERDE}▶ PASO $1: $2${NC}"; }
escribir_info()   { echo -e "  ${AMARILLO}ℹ $1${NC}"; }
escribir_exito()  { echo -e "  ${VERDE}✅ $1${NC}"; }
escribir_advert() { echo -e "  ${MAGENTA}⚠ $1${NC}"; }
escribir_error()  { echo -e "  ${ROJO}❌ $1${NC}"; }
pausa()           { [[ "$RAPIDO" != true ]] && sleep "${1:-3}"; }
pausa_tecla()     { [[ "$RAPIDO" != true ]] && { echo -e "\n  ${GRIS}[Presione ENTER para continuar...]${NC}"; read -r; }; }

# Verificar directorio
if [[ ! -f "src/bandeja_simulada.py" ]]; then
    escribir_error "Ejecute este script desde la raíz del proyecto (donde está src/)"
    exit 1
fi

escribir_titulo "🎯 DEMO AUTOMATIZADA - MATCHING INTELIGENTE CASO 2"
echo -e "  ${GRIS}Requisitos: RF-07, RF-11, RF-13, RF-15, RF-16, RNF-04, RNF-02, RNF-09${NC}"
echo -e "  ${GRIS}Modo: $([ "$RAPIDO" = true ] && echo "RÁPIDO" || echo "NORMAL")${NC}"
pausa_tecla

# ──────────────────────────────────────────────────────────────
# PASO 1: Ver la bandeja simulada
# ──────────────────────────────────────────────────────────────
escribir_paso 1 "BANDEJA SIMULADA - Fuente de datos (RF-15)"
escribir_info "Archivo: data/bandeja.json — 12 correos repartidos en ~19 horas simuladas"
escribir_info "Contiene: 4 vacantes con vacante_estructurada (V001-V004), 1 reenvío (b4), 1 gestión (b0), 2 candidatos (b6,b10), 4 basura (b7-b9), 1 incompleta (b5)"

python3 -c "
import json
with open('data/bandeja.json', 'r', encoding='utf-8-sig') as f:
    b = json.load(f)
print(f'Inicio simulado: {b[\"inicio\"]}')
print(f'Total correos: {len(b[\"correos\"])}')
for c in b['correos']:
    ve = c.get('vacante_estructurada')
    tag = f' → VACANTE {ve[\"id\"]} ({ve[\"scenario\"]})' if ve else ''
    reenvio = f' (reenvío de {c[\"reenvio_de\"]})' if c.get('reenvio_de') else ''
    nota = c.get('nota', '')
    print(f'  {c[\"message_id\"]:3s} @ {c[\"timestamp\"][11:16]} | {c[\"asunto\"][:55]:55s} {tag}{reenvio} {nota}')
"
pausa_tecla

# ──────────────────────────────────────────────────────────────
# PASO 2: Ejecutar bandeja simulada
# ──────────────────────────────────────────────────────────────
escribir_paso 2 "SIMULACIÓN HORA A HORA - RF-15 + RF-16 + RF-13"
escribir_info "Cada ciclo = 1 hora simulada. Solo correos de VACANTE disparan matching."
escribir_info "Reenvíos → duplicados (no disparan). Gestión/candidatos/basura → no_relacionado."
escribir_info "Vacante sin skills (b5) → revisión_humana (no se inventan criterios)."
escribir_info "Cola procesa vacantes en orden de llegada (RF-13). Límite 24h (RNF-04)."

RITMO="0.5"
[[ "$RAPIDO" = true ]] && RITMO="0"
echo -e "  ${GRIS}Comando: python -m src.bandeja_simulada --reiniciar --horas $HORAS_DEMO --ritmo-real $RITMO${NC}\n"
python -m src.bandeja_simulada --reiniciar --horas "$HORAS_DEMO" --ritmo-real "$RITMO"
pausa_tecla

if [[ "$SOLO_BANDEJA" = true ]]; then
    escribir_titulo "✅ DEMO BANDEJA COMPLETADA (modo --solo-bandeja)"
    exit 0
fi

# ──────────────────────────────────────────────────────────────
# PASO 3: Ver reportes generados
# ──────────────────────────────────────────────────────────────
escribir_paso 3 "REPORTES POR VACANTE - RF-11"
escribir_info "Cada vacante genera: reporte_<id>.md (ejecutivo), reporte_<id>.json (completo), auditoria_<id>.csv, shortlist_<id>.csv"

for r in reports/reporte_V*.md; do
    [[ -f "$r" ]] || continue
    vid=$(basename "$r" .md | sed 's/reporte_//')
    kb=$(du -k "$r" | cut -f1)
    escribir_exito "Reporte $vid generado (${kb} KB)"
done

primer=$(ls reports/reporte_V*.md 2>/dev/null | head -1)
if [[ -n "$primer" ]]; then
    escribir_info "Vista previa del reporte $(basename "$primer" .md | sed 's/reporte_//'):"
    head -40 "$primer" | sed 's/^/  /'
    echo -e "  ${GRIS}...${NC}"
fi
pausa_tecla

# ──────────────────────────────────────────────────────────────
# PASO 4: Matching manual
# ──────────────────────────────────────────────────────────────
escribir_paso 4 "MATCHING MANUAL - Vacante V001 (fácil) - RF-07 + RNF-04"
escribir_info "Ejecuta el grafo LangGraph con límites: máx 3 relajaciones, 3 consultas reclutador, 400 pasos, 30 llamadas LLM"
escribir_info "Modo: without_llm (determinístico, puntaje en código, LLM solo para redacción)"

python -m src.ejecutar_matching V001 --salida data/salida_demo_V001.json
pausa_tecla

# ──────────────────────────────────────────────────────────────
# PASO 5: Ver auditoría (RF-10)
# ──────────────────────────────────────────────────────────────
escribir_paso 5 "AUDITORÍA PASO A PASO - RF-10 (4 columnas: iteración, nodo, decisión, motivo)"
escribir_info "Archivo: reports/auditoria_V001.csv"

echo ""
head -15 reports/auditoria_V001.csv | column -t -s,
total=$(wc -l < reports/auditoria_V001.csv)
echo -e "  ${GRIS}... ($((total-1)) eventos totales)${NC}"
pausa_tecla

# ──────────────────────────────────────────────────────────────
# PASO 6: Consultas al reclutador (RF-04)
# ──────────────────────────────────────────────────────────────
escribir_paso 6 "CONSULTAS AL RECLUTADOR - RF-04 (máx 3 por corrida)"
escribir_info "Si el candidato no trae availability_date, se pregunta al reclutador simulado (data/reclutador.json)"
escribir_info "Respuesta 'no se sabe' o sin respuesta → campo vacío → 0 puntos en disponibilidad (no se inventa)"

# Extraer tabla del reporte markdown
awk '/## Consultas al reclutador/,/^## /' reports/reporte_V001.md | head -20 | sed 's/^/  /'
pausa_tecla

# ──────────────────────────────────────────────────────────────
# PASO 7: Relajaciones aplicadas
# ──────────────────────────────────────────────────────────────
escribir_paso 7 "RELAJACIONES AUTOMÁTICAS - RF-06/RF-07 (máx 3, skills obligatorios NUNCA)"
escribir_info "Orden: 1) Fecha +2 sem, 2) Experiencia -1 año, 3) Inglés -1 nivel"
escribir_info "Se detienen al conseguir 3 candidatos que superen umbral (70 pts) y cubran los 3 puestos"

awk '/## Criterios relajados/,/^## /' reports/reporte_V001.md | head -15 | sed 's/^/  /'
pausa_tecla

# ──────────────────────────────────────────────────────────────
# PASO 8: Clasificación correos reales (opcional)
# ──────────────────────────────────────────────────────────────
if [[ -f ".env" ]] && grep -q "AGENTMAIL_API_KEY" .env; then
    escribir_paso 8 "CLASIFICACIÓN CORREOS REALES - AgentMail (RNF-09)"
    escribir_info "Lee la bandeja real y clasifica sin procesar (modo verificación)"
    echo ""
    python -m src.verificar_correos
    pausa_tecla
else
    escribir_advert "PASO 8 omitido: AGENTMAIL_API_KEY no configurado en .env"
    pausa 1
fi

# ──────────────────────────────────────────────────────────────
# PASO 9: Verificar candidatos
# ──────────────────────────────────────────────────────────────
escribir_paso 9 "VERIFICACIÓN CANDIDATOS - Correos que describen perfiles"
escribir_info "Los correos clasificados como 'candidato' se guardan en data/candidatos.csv para futuros matchings"
python -m src.verificar_correos 2>/dev/null || escribir_advert "Requiere bandeja AgentMail configurada"
pausa_tecla

# ──────────────────────────────────────────────────────────────
# PASO 10: Resumen de archivos
# ──────────────────────────────────────────────────────────────
escribir_paso 10 "RESUMEN DE ARTEFACTOS GENERADOS"
echo ""
echo -e "  ${CIAN}data/${NC}"
echo "    ├── bandeja.json              # Bandeja simulada (fuente)"
echo "    ├── bandeja_procesados.json   # IDs ya procesados (persistencia)"
echo "    ├── cola_vacantes.json        # Cola de vacantes de la corrida"
echo "    ├── vacantes.json             # Catálogo maestro"
echo "    ├── candidatos.csv            # 41 perfiles base + nuevos de correos"
echo "    └── reclutador.json           # Respuestas simuladas disponibilidad"
echo ""
echo -e "  ${CIAN}reports/${NC}"
for a in reports/*; do
    [[ -f "$a" ]] || continue
    kb=$(du -k "$a" | cut -f1)
    echo "    ├── $(basename "$a") (${kb} KB)"
done
echo ""
echo -e "  ${CIAN}logs/${NC}"
for a in logs/*; do
    [[ -f "$a" ]] || continue
    kb=$(du -k "$a" | cut -f1)
    echo "    ├── $(basename "$a") (${kb} KB)"
done

# ──────────────────────────────────────────────────────────────
# CIERRE
# ──────────────────────────────────────────────────────────────
escribir_titulo "✅ DEMO COMPLETADA"
echo -e "  ${VERDE}Todos los requisitos demostrados:${NC}"
echo "  • RF-15: Bandeja simulada hora a hora (ciclos 1h, max 24h)"
echo "  • RF-16: Clasificación 4 clases + cola de vacantes"
echo "  • RF-13: Cola procesa múltiples vacantes en orden (V001→V002→V003→V004)"
echo "  • RF-11: Reporte .md + .json + CSV por vacante"
echo "  • RF-10: Auditoría 4 columnas (iteración, nodo, decisión, motivo)"
echo "  • RF-07 + RNF-04: Parada 3 relajaciones, límites grafo (400 pasos)"
echo "  • RF-04: Consultas reclutador (máx 3, 'no se sabe' = 0 pts)"
echo "  • RNF-02: Modo without_llm determinístico"
echo "  • RNF-09: Sin credenciales en código (.env para AgentMail)"
echo ""
echo -e "  ${AMARILLO}Para demo con AgentMail real:${NC}"
echo "    1. Configure AGENTMAIL_API_KEY y AGENTMAIL_INBOX_ID en .env"
echo "    2. Ejecute: python -m src.leer_correos --vigilar"
echo ""
pausa_tecla