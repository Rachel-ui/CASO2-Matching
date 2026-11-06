<# Demo CASO 2 - Matching Inteligente #>
param([switch]$Rapido,[switch]$SoloBandeja,[int]$HorasDemo=8)

$V="Green";$A="Yellow";$C="Cyan";$M="Magenta";$G="DarkGray";$R="Red"

if(-not(Test-Path "src\bandeja_simulada.py")){Write-Host"  [ERR] Ejecute desde la raiz (src/)" -Fore $R;exit 1}

Write-Host "`n$(('='*70))" -Fore $C;Write-Host"  DEMO MATCHING INTELIGENTE CASO 2" -Fore $C;Write-Host"$(('='*70))`n" -Fore $C
Write-Host"  RF-07,11,13,15,16, RNF-04,02,09" -Fore $G
Write-Host"  Modo: $(if($Rapido){'RAPIDO'}else{'NORMAL'})" -Fore $G
if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}

# PASO 1
Write-Host"`n==> PASO 1: BANDEJA SIMULADA (RF-15)" -Fore $V
Write-Host"  [*] data/bandeja.json - 12 correos, ~19h. 4 vacantes V001-V004, 1 reenvio, 1 gestion, 2 candidatos, 4 basura, 1 incompleta" -Fore $A
python -c "
import json
with open('data/bandeja.json','r',encoding='utf-8-sig') as f:b=json.load(f)
print(f'Inicio: {b[\"inicio\"]}');print(f'Total: {len(b[\"correos\"])}')
for c in b['correos']:
    ve=c.get('vacante_estructurada');t=f' -> VACANTE {ve[\"id\"]} ({ve[\"scenario\"]})'if ve else''
    r=f' (reenvio {c[\"reenvio_de\"]})'if c.get('reenvio_de')else'';n=c.get('nota','')
    print(f'  {c[\"message_id\"]:3s} @ {c[\"timestamp\"][11:16]} | {c[\"asunto\"][:55]:55s}{t}{r}{n}')
"
if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}

# PASO 2
Write-Host"`n==> PASO 2: SIMULACION HORA A HORA (RF-15+16+13)" -Fore $V
Write-Host"  [*] 1 ciclo=1h. Solo VACANTE dispara matching. Reenvios=duplicados. Gestion/candidatos/basura=no_relacionado." -Fore $A
Write-Host"  [*] Vacante sin skills=revision_humana. Cola orden llegada. Max 24h." -Fore $A
$cmd="python -m src.bandeja_simulada --reiniciar --horas $HorasDemo";if($Rapido){$cmd+=" --ritmo-real 0"}else{$cmd+=" --ritmo-real 0.5"}
Write-Host"  [*] Cmd: $cmd" -Fore $A;Write-Host"";Invoke-Expression $cmd
if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}
if($SoloBandeja){Write-Host"`n$(('='*70))" -Fore $C;Write-Host"  BANDEJA OK" -Fore $C;Write-Host"$(('='*70))" -Fore $C;exit 0}

# PASO 3
Write-Host"`n==> PASO 3: REPORTES (RF-11)" -Fore $V
Write-Host"  [*] Cada vacante: reporte.md, .json, auditoria.csv, shortlist.csv" -Fore $A
$rs=Get-ChildItem reports/reporte_V*.md|Sort Name
$rs|%{$v=$_.BaseName-replace'reporte_','';Write-Host"  [OK] Reporte $v ($([math]::Round($_.Length/1024,1)) KB)" -Fore $V}
$p=$rs[0];Write-Host"  [*] Vista: $($p.BaseName-replace'reporte_','')" -Fore $A
Get-Content $p.FullName|Select -First 40|%{Write-Host"  $_" -Fore $G};Write-Host"  ..." -Fore $G
if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}

# PASO 4
Write-Host"`n==> PASO 4: MATCHING V001 (RF-07+RNF-04)" -Fore $V
Write-Host"  [*] Grafo: max 3 relajaciones, 3 consultas, 400 pasos, 30 LLM. Modo without_llm." -Fore $A
python -m src.ejecutar_matching V001 --salida data/salida_demo_V001.json
if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}

# PASO 5
Write-Host"`n==> PASO 5: AUDITORIA (RF-10)" -Fore $V
Write-Host"  [*] reports/auditoria_V001.csv (iteracion, nodo, decision, motivo)" -Fore $A
Write-Host"";Import-Csv reports/auditoria_V001.csv|Select -First 15|Format-Table -Auto|Out-Host
$cnt=(Import-Csv reports/auditoria_V001.csv).Count;Write-Host"  ... $cnt eventos" -Fore $G
if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}

# PASO 6
Write-Host"`n==> PASO 6: CONSULTAS RECLUTADOR (RF-04)" -Fore $V
Write-Host"  [*] Sin availability_date -> reclutador. 'no se sabe' = 0 pts." -Fore $A
$r=Get-Content reports/reporte_V001.md -Raw
if($r-match'(?s)## Consultas al reclutador.*?\|(.*?)\n##'){$matches[1].Trim().Split('\n')|Where{$_-match'\|'}|Select -First 10|%{Write-Host"  $_" -Fore $G}}
if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}

# PASO 7
Write-Host"`n==> PASO 7: RELAJACIONES (RF-06/07)" -Fore $V
Write-Host"  [*] Max 3: 1)Fecha+2sem 2)Exp-1ano 3)Ingles-1nivel. Skills obligatorios NUNCA." -Fore $A
$r=Get-Content reports/reporte_V001.md -Raw
if($r-match'(?s)## Criterios relajados.*?\|(.*?)\n##'){$matches[1].Trim().Split('\n')|Where{$_-match'\|'}|%{Write-Host"  $_" -Fore $G}}
if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}

# PASO 8
if(Test-Path ".env"){$e=Get-Content .env -Raw;if($e-match'AGENTMAIL_API_KEY'){Write-Host"`n==> PASO 8: AGENTMAIL (RNF-09)" -Fore $V;Write-Host"  [*] Lee bandeja real, clasifica" -Fore $A;Write-Host"";python -m src.verificar_correos;if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}}else{Write-Host"  [!] PASO 8: sin AGENTMAIL_API_KEY" -Fore $M;if(-not$Rapido){Start-Sleep 1}}}else{Write-Host"  [!] PASO 8: sin .env" -Fore $M;if(-not$Rapido){Start-Sleep 1}}

# PASO 9
Write-Host"`n==> PASO 9: VERIFICACION CANDIDATOS" -Fore $V
Write-Host"  [*] Correos 'candidato' -> data/candidatos.csv" -Fore $A
python -m src.verificar_correos 2>$null;if($LASTEXITCODE-ne0){Write-Host"  [!] Requiere AgentMail" -Fore $M}
if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}

# PASO 10
Write-Host"`n==> PASO 10: ARTEFACTOS" -Fore $V
Write-Host"";Write-Host"  data/" -Fore $C
"bandeja.json","bandeja_procesados.json","cola_vacantes.json","vacantes.json","candidatos.csv","reclutador.json"|%{Write-Host"    +-- $_" -Fore $G}
Write-Host"";Write-Host"  reports/" -Fore $C
Get-ChildItem reports/ -File|Sort Name|%{Write-Host"    +-- $($_.Name) ($([math]::Round($_.Length/1024,1)) KB)" -Fore $G}
Write-Host"";Write-Host"  logs/" -Fore $C
Get-ChildItem logs/ -File|%{Write-Host"    +-- $($_.Name) ($([math]::Round($_.Length/1024,1)) KB)" -Fore $G}

# CIERRE
Write-Host"`n$(('='*70))" -Fore $C;Write-Host"  DEMO COMPLETADA" -Fore $C;Write-Host"$(('='*70))`n" -Fore $C
Write-Host"  Requisitos demostrados:" -Fore $V
"RF-15: Bandeja 1h/24h","RF-16: 4 clases+cola","RF-13: Cola V001->V004","RF-11: .md+.json+CSV","RF-10: Auditoria 4 cols","RF-07+RNF-04: 3 relajaciones/400 pasos","RF-04: 3 consultas, no_se_sabe=0","RNF-02: without_llm deterministico","RNF-09: .env sin credenciales"|%{Write-Host"  * $_"}
Write-Host"";Write-Host"  AgentMail real:" -Fore $A;"  1. AGENTMAIL_API_KEY+INBOX_ID en .env";"  2. python -m src.leer_correos --vigilar"
if(-not$Rapido){Write-Host"`n  [ENTER...]" -Fore $G -NoNewline;Read-Host|Out-Null}