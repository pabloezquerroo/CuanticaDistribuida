# Prueba de lectura de S3 con Backblaze B2

import boto3
import os   
import dotenv
import json

dotenv.load_dotenv()

backblaze_endpoint_url = os.getenv('S3_ENDPOINT_URL')
backblaze_key_id = os.getenv('AWS_ACCESS_KEY_ID')
backblaze_application_key = os.getenv('AWS_SECRET_ACCESS_KEY')
backblaze_bucket_name = os.getenv('S3_BUCKET_NAME') 

# Inicializar el cliente Boto3 S3
s3 = boto3.client(
    's3',
    endpoint_url=backblaze_endpoint_url,
    aws_access_key_id=backblaze_key_id,
    aws_secret_access_key=backblaze_application_key
)

# Subir config.json a Backblaze B2
config = { 
    "codeConfig": [72, 90], # Posibles codigos: 72, 90, 108, 144, 288, 784
    "p": [0.001, 0.002],  # Posibles tasas de error fisicas: 0.001, 0.002, 0.003, 0.004, 0.005
    "NMCs": [100, 100],
    "NMCs_batch_size": 10, # Numero de iteraciones por lote de NMCs
    "args_batch_size": 10, # Numero de argumentos por lote de args
}

object_key = f"{os.getenv('S3_CONFIG_FILE_PATH')}" 
json_data = json.dumps(config, indent=4)

try:
    s3.put_object(
        Bucket=backblaze_bucket_name,
        Key=object_key,
        Body=json_data,
        ContentType='application/json' 
    )
    print(f"Objeto '{object_key}' subido exitosamente al bucket '{backblaze_bucket_name}' en Backblaze B2.")
except Exception as e:
    print(f"Error al subir el objeto a Backblaze B2: {e}")


# Listar los objetos en el bucket
# try:
#     response = s3.list_objects_v2(Bucket=backblaze_bucket_name)
#     if 'Contents' in response:
#         print("Objetos en el bucket:")
#         for obj in response['Contents']:
#             print(f"- {obj['Key']}")
#     else:
#         print("El bucket está vacío.")
# except Exception as e:
#     print(f"Error al listar los objetos en el bucket: {e}")


# Prueba de DynamoDB local
# try:
#     # Conecta a DynamoDB en el puerto 8001
#     dynamodb_client = boto3.client(
#         'dynamodb',
#         endpoint_url='http://localhost:8001',
#         region_name='us-west-2',
#         aws_access_key_id='dummy',
#         aws_secret_access_key='dummy'
#     )

#     dynamodb_client.create_table(
#             TableName='samples_dynamodb',
#             KeySchema=[
#                 {'AttributeName': 'id_nmc_batch', 'KeyType': 'HASH'}
#             ],
#             AttributeDefinitions=[
#                 {'AttributeName': 'id_nmc_batch', 'AttributeType': 'S'}
#             ],
#             ProvisionedThroughput={
#                 'ReadCapacityUnits': 5,
#                 'WriteCapacityUnits': 5
#             }
#         )
#     print(f"Tabla 'samples_dynamodb' creada exitosamente.")

#     # Intenta listar las tablas (aunque no haya ninguna)
#     tables = dynamodb_client.list_tables()

#     # Elimina la tabla
#     dynamodb_client.delete_table(TableName='samples_dynamodb')
    
#     print("¡ÉXITO! La conexión con DynamoDB local funciona.")
#     print(f"Tablas encontradas: {tables['TableNames']}")

# except Exception as e:
#     print(f"ERROR: No se pudo conectar a DynamoDB local.")
#     print(f"Detalle: {e}")
