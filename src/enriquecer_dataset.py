
import csv
from pathlib import Path

ARCHIVO = Path("data/candidatos.csv")

# Leer el CSV original conservando los caracteres UTF-8.
with ARCHIVO.open("r", encoding="utf-8-sig", newline="") as archivo:
    lector = csv.DictReader(archivo)
    columnas_originales = lector.fieldnames
    candidatos = list(lector)

if not columnas_originales:
    raise ValueError("El CSV no contiene encabezados.")

if len(candidatos) != 40:
    raise ValueError(
        f"Se esperaban 40 candidatos, pero se encontraron {len(candidatos)}."
    )

# Asignar un rol sintético según las habilidades del perfil.
def asignar_rol(candidato):
    skills = {
        skill.strip().lower()
        for skill in candidato["skills"].split(";")
    }

    if "java" in skills:
        return "Desarrollador Backend Java"

    if "react" in skills or "node.js" in skills:
        return "Desarrollador Full Stack JavaScript"

    return "Desarrollador Backend Python"


# Crear teléfonos ficticios para las pruebas.
# Los perfiles duplicados comparten teléfono cuando corresponde.
telefonos = {
    candidato["id"]: f"FICTICIO-{int(candidato['id'][1:]):03d}"
    for candidato in candidatos
}

# C001 y C032 comparten correo y teléfono.
telefonos["C032"] = telefonos["C001"]

# C023 y C031 comparten nombre y teléfono.
telefonos["C031"] = telefonos["C023"]

# Agregar los nuevos campos sin eliminar los existentes.
for candidato in candidatos:
    candidato["rol"] = asignar_rol(candidato)
    candidato["telefono"] = telefonos[candidato["id"]]

columnas_nuevas = list(columnas_originales)

for columna in ("rol", "telefono"):
    if columna not in columnas_nuevas:
        columnas_nuevas.append(columna)

# Guardar en UTF-8 y conservar el orden de los registros.
with ARCHIVO.open("w", encoding="utf-8", newline="") as archivo:
    escritor = csv.DictWriter(
        archivo,
        fieldnames=columnas_nuevas,
        extrasaction="ignore",
    )
    escritor.writeheader()
    escritor.writerows(candidatos)

print("Dataset actualizado correctamente.")
print(f"Total de candidatos: {len(candidatos)}")
print(f"Columnas: {', '.join(columnas_nuevas)}")
print("Se añadieron los roles y teléfonos ficticios.")