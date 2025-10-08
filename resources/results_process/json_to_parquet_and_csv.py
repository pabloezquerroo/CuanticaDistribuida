import json
import pandas as pd
import csv

# Función recursiva para convertir el formato de DynamoDB a Python nativo
def dynamodb_to_python(item):
    if "S" in item:
        return item["S"]
    elif "N" in item:
        # Convertir a número (int si es entero, float en otro caso)
        num = float(item["N"])
        return int(num) if num.is_integer() else num
    elif "M" in item:
        return {k: dynamodb_to_python(v) for k, v in item["M"].items()}
    elif "L" in item:
        return [dynamodb_to_python(v) for v in item["L"]]
    else:
        return None

# Cargar JSON desde archivo
with open("results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# Obtener el array Items de la respuesta de DynamoDB
items = data.get('Items', [])

# Convertir cada objeto del array Items
records = [{k: dynamodb_to_python(v) for k, v in obj.items()} for obj in items]

# Pasar a DataFrame
df = pd.DataFrame(records)

# Mantener la estructura anidada en el CSV/Parquet serializando listas y dicts como JSON en cada celda
def to_serializable(x):
    if x is None:
        return ""
    if isinstance(x, (dict, list)):
        return json.dumps(x, ensure_ascii=False)
    return x

df_serial = df.applymap(to_serializable)

# Guardar en Parquet (las estructuras anidadas ya están serializadas como strings)
df_serial.to_parquet("results.parquet", engine="pyarrow", index=False)

# CSV legible: separador ';' (cambia a ',' si prefieres), codificación utf-8, quoting mínimo
df_serial.to_csv("results.csv", sep=';', index=False, encoding='utf-8', quoting=csv.QUOTE_MINIMAL)

print("Conversión completada: results.parquet y results.csv generados (CSV con ';' como delimitador).")
