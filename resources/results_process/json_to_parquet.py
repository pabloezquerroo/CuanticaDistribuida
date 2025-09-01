import json
import pandas as pd

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
with open("results.json", "r") as f:
    data = json.load(f)

# Convertir cada objeto del JSON
records = [{k: dynamodb_to_python(v) for k, v in obj.items()} for obj in data]

# Pasar a DataFrame
df = pd.DataFrame(records)

# Guardar en Parquet
df.to_parquet("results.parquet", engine="pyarrow", index=False)

print("Conversión completada: results.parquet")
