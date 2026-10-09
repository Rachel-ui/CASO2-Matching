
import csv
import json
from datetime import date
from pathlib import Path

import yaml


# Ubicación raíz del proyecto
RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


def revisar_candidatos():
    ruta = DATA / "candidatos.csv"

    with ruta.open("r", encoding="utf-8-sig", newline="") as archivo:
        candidatos = list(csv.DictReader(archivo))

    campos = {
        "id",
        "nombre",
        "email",
        "skills",
        "experience_years",
        "english_level",
        "availability_date",
        "modality",
    }

    if not candidatos:
        raise ValueError("El CSV no contiene candidatos.")

    faltantes = campos - set(candidatos[0].keys())
    if faltantes:
        raise ValueError(f"Faltan columnas en candidatos.csv: {faltantes}")

    ids = [c["id"].strip() for c in candidatos]
    ids_duplicados = sorted({
        identificador
        for identificador in ids
        if ids.count(identificador) > 1
    })

    niveles = {"A1", "A2", "B1", "B2", "C1", "C2"}
    modalidades = {"remoto", "hibrido", "presencial"}
    errores = []

    for candidato in candidatos:
        identificador = candidato["id"].strip()

        if not identificador or not candidato["nombre"].strip():
            errores.append(f"{identificador or '(sin ID)'}: falta ID o nombre")

        if not candidato["email"].strip():
            errores.append(f"{identificador}: falta email")

        try:
            experiencia = int(candidato["experience_years"])
            if experiencia < 0:
                errores.append(f"{identificador}: experiencia negativa")
        except (ValueError, TypeError):
            errores.append(f"{identificador}: experiencia no válida")

        if candidato["english_level"].strip() not in niveles:
            errores.append(f"{identificador}: nivel de inglés no válido")

        if candidato["modality"].strip().lower() not in modalidades:
            errores.append(f"{identificador}: modalidad no válida")

        fecha = candidato["availability_date"].strip()
        if fecha:
            try:
                date.fromisoformat(fecha)
            except ValueError:
                errores.append(f"{identificador}: fecha no válida ({fecha})")

        skills = candidato["skills"].strip().split(";")
        if not candidato["skills"].strip() or any(not s.strip() for s in skills):
            errores.append(f"{identificador}: habilidades vacías o mal separadas")

    print("\n=== CANDIDATOS ===")
    print(f"Total de candidatos: {len(candidatos)}")
    print(f"IDs únicos: {len(set(ids))}")
    print(f"IDs duplicados: {ids_duplicados or 'ninguno'}")
    print(
        "Candidatos sin fecha de disponibilidad:",
        sum(not c["availability_date"].strip() for c in candidatos),
    )

    if errores:
        print("Errores encontrados:")
        for error in errores:
            print(f"- {error}")
    else:
        print("Validaciones de campos: sin errores.")

    return candidatos, errores, ids_duplicados


def revisar_vacantes():
    ruta = DATA / "vacantes.json"

    with ruta.open("r", encoding="utf-8-sig") as archivo:
        datos = json.load(archivo)

    vacantes = datos.get("vacantes", [])
    ids = [v.get("id", "").strip() for v in vacantes]
    errores = []

    campos = {
        "id",
        "titulo",
        "descripcion",
        "skills_obligatorios",
        "skills_deseables",
        "experience_required",
        "english_required",
        "availability_required",
        "modality",
    }

    niveles = {"A1", "A2", "B1", "B2", "C1", "C2"}
    modalidades = {"remoto", "hibrido", "presencial"}

    if not vacantes:
        errores.append("No se encontraron vacantes.")

    if len(ids) != len(set(ids)):
        errores.append("Hay IDs de vacantes duplicados.")

    for vacante in vacantes:
        identificador = vacante.get("id", "(sin ID)")
        faltantes = campos - set(vacante.keys())

        if faltantes:
            errores.append(f"{identificador}: faltan campos {sorted(faltantes)}")

        if not vacante.get("titulo", "").strip():
            errores.append(f"{identificador}: falta título")

        for campo in ("skills_obligatorios", "skills_deseables"):
            skills = vacante.get(campo)
            if not isinstance(skills, list) or any(
                not isinstance(skill, str) or not skill.strip()
                for skill in skills
            ):
                errores.append(f"{identificador}: {campo} no tiene formato válido")

        try:
            experiencia = int(vacante["experience_required"])
            if experiencia < 0:
                errores.append(f"{identificador}: experiencia requerida negativa")
        except (ValueError, TypeError, KeyError):
            errores.append(f"{identificador}: experiencia requerida no válida")

        if vacante.get("english_required") not in niveles:
            errores.append(f"{identificador}: nivel de inglés requerido no válido")

        if vacante.get("modality") not in modalidades:
            errores.append(f"{identificador}: modalidad no válida")

        try:
            date.fromisoformat(vacante["availability_required"])
        except (ValueError, TypeError, KeyError):
            errores.append(f"{identificador}: fecha requerida no válida")

    print("\n=== VACANTES ===")
    print(f"Total de vacantes: {len(vacantes)}")
    print(f"IDs: {ids}")

    for vacante in vacantes:
        print(
            f"- {vacante.get('id')}: {vacante.get('titulo')} "
            f"(experiencia: {vacante.get('experience_required')}, "
            f"inglés: {vacante.get('english_required')})"
        )

    if errores:
        print("Errores encontrados:")
        for error in errores:
            print(f"- {error}")
    else:
        print("Validaciones de campos: sin errores.")

    return vacantes, errores


def revisar_configuracion():
    ruta = DATA / "config.yaml"

    with ruta.open("r", encoding="utf-8-sig") as archivo:
        config = yaml.safe_load(archivo)

    errores = []

    if not isinstance(config, dict):
        errores.append("La configuración debe ser un objeto YAML.")
        config = {}

    scoring = config.get("scoring", {})
    pesos = scoring.get("weights", {})

    if not isinstance(pesos, dict) or not pesos:
        errores.append("No se encontraron los pesos de scoring.")
    else:
        try:
            valores = [float(valor) for valor in pesos.values()]
            if any(valor < 0 for valor in valores):
                errores.append("Hay pesos negativos.")
            if sum(valores) != 100:
                errores.append(
                    f"Los pesos suman {sum(valores)}, no 100."
                )
        except (ValueError, TypeError):
            errores.append("Hay pesos que no son numéricos.")

    print("\n=== CONFIGURACIÓN ===")
    print(f"Umbral de puntuación: {scoring.get('threshold')}")
    print(f"Pesos: {pesos}")
    print(f"Suma de pesos: {sum(pesos.values()) if pesos else 'no disponible'}")

    if errores:
        print("Errores encontrados:")
        for error in errores:
            print(f"- {error}")
    else:
        print("Validaciones de configuración: sin errores.")

    return errores


if __name__ == "__main__":
    print("VALIDACIÓN DEL DATASET CASO2-Matching")

    _, errores_candidatos, duplicados = revisar_candidatos()
    _, errores_vacantes = revisar_vacantes()
    errores_configuracion = revisar_configuracion()

    print("\n=== RESUMEN ===")
    print(f"IDs duplicados de candidatos: {duplicados or 'ninguno'}")

    total_errores = (
        len(errores_candidatos)
        + len(errores_vacantes)
        + len(errores_configuracion)
    )

    print(f"Total de problemas detectados: {total_errores}")