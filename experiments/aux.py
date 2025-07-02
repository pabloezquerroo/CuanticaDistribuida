# Prueba de lectura de S3 con Backblaze B2

import boto3
import os   
import dotenv
import json

# Cargar las variables de entorno desde el archivo .env
dotenv.load_dotenv()

# Obtener las credenciales y el endpoint de Backblaze B2
# Estas variables se cargan desde tu archivo .env
backblaze_endpoint_url = os.getenv('S3_ENDPOINT_URL')
backblaze_key_id = os.getenv('AWS_ACCESS_KEY_ID')
backblaze_application_key = os.getenv('AWS_SECRET_ACCESS_KEY')

# Opcional: Cargar el nombre del bucket desde .env si lo definiste allí
# backblaze_bucket_name = os.getenv('B2_BUCKET_NAME', 'tu-nombre-de-bucket-por-defecto')
# Si no lo tienes en .env, define el nombre del bucket directamente aquí:
backblaze_bucket_name = os.getenv('S3_BUCKET_NAME') # <-- ¡IMPORTANTE! Reemplaza con el nombre real de tu bucket en Backblaze B2

# Inicializar el cliente Boto3 S3
# Es crucial pasar el 'endpoint_url' para que apunte a Backblaze B2
s3 = boto3.client(
    's3',
    endpoint_url=backblaze_endpoint_url,
    aws_access_key_id=backblaze_key_id,
    aws_secret_access_key=backblaze_application_key
)

# Tu diccionario de configuración (el JSON que quieres subir)
config = { 
    "codeConfig": [72, 90], # Posibles codigos: 72, 90, 108, 144, 288, 784
    "p": [0.001, 0.002],  # Posibles tasas de error fisicas: 0.001, 0.002, 0.003, 0.004, 0.005
    "NMCs": [1000, 1000],
    "NMCs_batch": 100, # Numero de iteraciones por lote
}

# Definir la "clave" (nombre de archivo) para el objeto en Backblaze B2
object_key = f"{os.getenv('CONFIG_FILE_PATH')}" # Puedes elegir el nombre que quieras para el archivo en B2

# Convertir el diccionario a una cadena JSON
json_data = json.dumps(config, indent=4) # indent=4 para una salida JSON más legible

# Subir el objeto JSON a Backblaze B2
# try:
#     s3.put_object(
#         Bucket=backblaze_bucket_name,
#         Key=object_key,
#         Body=json_data,
#         ContentType='application/json' # Muy recomendado para indicar el tipo de archivo
#     )
#     print(f"Objeto '{object_key}' subido exitosamente al bucket '{backblaze_bucket_name}' en Backblaze B2.")
# except Exception as e:
#     print(f"Error al subir el objeto a Backblaze B2: {e}")


# Listar los objetos en el bucket
try:
    response = s3.list_objects_v2(Bucket=backblaze_bucket_name)
    if 'Contents' in response:
        print("Objetos en el bucket:")
        for obj in response['Contents']:
            print(f"- {obj['Key']}")
    else:
        print("El bucket está vacío.")
except Exception as e:
    print(f"Error al listar los objetos en el bucket: {e}")


