# Prueba de lectura de S3 con Backblaze B2

import boto3
import os   
import dotenv
import json

dotenv.load_dotenv()

# Inicializar el cliente Boto3 S3
# s3 = boto3.client(
#     's3',
#     endpoint_url=os.getenv('S3_ENDPOINT_URL'),
#     aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
#     aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
# )

# Subir config.json a Backblaze B2
# config = { 
#     "codeConfig": [72, 90], # Posibles codigos: 72, 90, 108, 144, 288, 784
#     "p": [0.001, 0.002],  # Posibles tasas de error fisicas: 0.001, 0.002, 0.003, 0.004, 0.005
#     "NMCs": [100, 100],
#     "NMCs_batch_size": 10, # Numero de iteraciones por lote de NMCs
#     "args_batch_size": 10, # Numero de argumentos por lote de args
# }

# object_key = f"{os.getenv('S3_CONFIG_FILE_PATH')}" 
# json_data = json.dumps(config, indent=4)

# try:
#     s3.put_object(
#         Bucket=os.getenv('S3_BUCKET_NAME'),
#         Key=object_key,
#         Body=json_data,
#         ContentType='application/json' 
#     )
#     print(f"Objeto '{object_key}' subido exitosamente al bucket '{os.getenv('S3_BUCKET_NAME')}' en Backblaze B2.")
# except Exception as e:
#     print(f"Error al subir el objeto a Backblaze B2: {e}")


# Listar los objetos en el bucket
# try:
#     response = s3.list_objects_v2(Bucket=os.getenv('S3_BUCKET_NAME'))
#     if 'Contents' in response:
#         print("Objetos en el bucket:")
#         for obj in response['Contents']:
#             print(f"- {obj['Key']}")
#     else:
#         print("El bucket está vacío.")
# except Exception as e:
#     print(f"Error al listar los objetos en el bucket: {e}")


# Creación tablas DynamoDB local

def get_connection_dynamodb():
    return boto3.resource(
        'dynamodb',
        region_name=os.getenv('AWS_DEFAULT_REGION'),
        endpoint_url=os.getenv('DYNAMODB_ENDPOINT_URL'),
        aws_access_key_id='dummy',
        aws_secret_access_key='dummy'
    )

def create_table(table_name):
    try:
        dynamodb_client= get_connection_dynamodb()
        
        dynamodb_client.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'id_nmc_batch', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'id_nmc_batch', 'AttributeType': 'S'}
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        print(f"Tabla '{table_name}' creada exitosamente.")
        
    except Exception as e:
        print(f"Error al crear la tabla '{table_name}': {e}")

try:
    create_table(os.getenv('DYNAMODB_SAMPLES_TABLE_NAME'))
    create_table(os.getenv('DYNAMODB_ARGS_TABLE_NAME'))
    print(f"Tablas 'samples_dynamodb' y 'args_dynamodb' creadas exitosamente.")

    # Intenta listar las tablas (aunque no haya ninguna)
    tables = dynamodb_client.list_tables()

    # Elimina la tabla
    dynamodb_client.delete_table(TableName='samples_dynamodb')
    
    print("¡ÉXITO! La conexión con DynamoDB local funciona.")
    print(f"Tablas encontradas: {tables['TableNames']}")

except Exception as e:
    print(f"ERROR: No se pudo conectar a DynamoDB local.")
    print(f"Detalle: {e}")
